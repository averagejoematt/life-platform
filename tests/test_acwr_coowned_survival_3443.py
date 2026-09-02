"""tests/test_acwr_coowned_survival_3443.py — the co-owned computed_metrics
record survives a from-scratch rebuild (#3443).

acwr-compute merges acwr_* onto the daily computed_metrics record via
update_item (~16:55Z); daily-metrics-compute rebuilds the record from scratch
and put_items it. 2026-08-24→09-01 the evening re-run (00:00Z) erased every
merged field nightly — 9 days dark, zero alarms. (Trigger: the #2811 PT-clock
correction re-aimed the evening re-put from UTC-yesterday, a wrong-record
latent bug that accidentally protected the merge, onto PT-yesterday — the
record ACWR had merged onto seven hours earlier. The #3135-fingerprint
hypothesis on the issue was refuted: evening recomputes fired both before and
after; what changed was WHICH record they re-put.)

Three contracts, all against the ONE registry in
compute.computed_metrics_contract:

  1. the contract test — store_computed_metrics (and the sick-day rebuild)
     carries every registered co-owned field through a from-scratch re-put;
  2. the derivation guard — the acwr writer's UpdateExpression writes exactly
     the registered set, so neither side can drift from the registry silently;
  3. the dead-man — qa_smoke's acwr_liveness check reds when the newest
     acwr_computed_at exceeds ACWR_MAX_AGE_HOURS (this incident would have
     paged on day 2).
"""

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from compute.computed_metrics_contract import ACWR_COOWNED_FIELDS, ACWR_MAX_AGE_HOURS  # noqa: E402


def _merged_fields():
    """A live-shaped set of values for every registered co-owned field."""
    return {
        "acwr": Decimal("0.945"),
        "acwr_zone": "safe",
        "acwr_alert": False,
        "acwr_alert_reason": "ACWR 0.94 is in the optimal 0.8-1.3 zone.",
        "acwr_computed_at": "2026-09-01T16:55:48.000000+00:00",
        "acwr_days_acute": Decimal("7"),
        "acwr_days_chronic": Decimal("28"),
        "acwr_method": "ewma",
        "acwr_coupling_caveat": "acute and chronic EWMAs share the same strain series",
        "acute_load_7d": Decimal("6.18"),
        "chronic_load_28d": Decimal("6.54"),
    }


def test_registry_covers_the_fixture_exactly():
    assert set(_merged_fields()) == set(ACWR_COOWNED_FIELDS)


# ──────────────────────────────────────────────────────────────────────────────
# 1. The contract test — the rebuild carries the merge through
# ──────────────────────────────────────────────────────────────────────────────


class _Table:
    def __init__(self, existing=None, get_raises=None):
        self.existing = existing
        self.get_raises = get_raises
        self.put_items = []

    def get_item(self, Key=None, **kwargs):
        if self.get_raises:
            raise self.get_raises
        if self.existing and Key == {"pk": self.existing["pk"], "sk": self.existing["sk"]}:
            return {"Item": dict(self.existing)}
        return {}

    def put_item(self, Item=None, **kwargs):
        self.put_items.append(Item)
        return {}


def _dmc():
    import daily_metrics_compute_lambda as dmc

    return dmc


def _store(monkeypatch, table):
    dmc = _dmc()
    monkeypatch.setattr(dmc, "table", table)
    dmc.store_computed_metrics(
        date_str="2026-09-01",
        day_grade_score=82.0,
        grade="B",
        component_scores={"sleep": 80},
        component_details={"sleep": {"hours": 7.5}},
        readiness_score=71,
        readiness_colour="yellow",
        streak_data={"tier0_streak": 3, "tier01_streak": 2},
        tsb=-4.5,
        hrv_7d=55.0,
        hrv_30d=52.0,
        sleep_debt_7d_hrs=3.5,
        latest_weight=318.2,
        week_ago_weight=320.0,
        avatar_weight=318.2,
    )
    assert len(table.put_items) == 1
    return table.put_items[0]


def test_rebuild_preserves_every_coowned_field(monkeypatch):
    """The incident shape verbatim: a record carrying the 16:55Z merge is
    re-put from scratch by the evening run — every merged field must survive."""
    existing = {"pk": "USER#matthew#SOURCE#computed_metrics", "sk": "DATE#2026-09-01", "date": "2026-09-01"}
    existing.update(_merged_fields())
    item = _store(monkeypatch, _Table(existing=existing))
    for f in ACWR_COOWNED_FIELDS:
        assert item[f] == _merged_fields()[f], f"co-owned field erased by the rebuild: {f}"
    # And the rebuild's own fields still won (this is a rebuild, not a revert).
    assert item["day_grade_letter"] == "B"


def test_first_write_of_the_day_carries_nothing(monkeypatch):
    item = _store(monkeypatch, _Table(existing=None))
    assert not any(f in item for f in ACWR_COOWNED_FIELDS)


def test_read_failure_is_loud_not_a_silent_erase(monkeypatch):
    """A transient get_item failure must fail the run, not quietly rebuild
    without the merge — a silent fail-open here IS the #3443 erasure."""
    with pytest.raises(RuntimeError):
        _store(monkeypatch, _Table(existing=None, get_raises=RuntimeError("throttled")))


def test_sick_day_rebuild_carries_the_fields_too():
    """Source pin for the second from-scratch rebuild of the co-owned record:
    the sick-day put must be preceded by the same registry-driven carry."""
    src = open(os.path.join(_REPO, "lambdas", "compute", "daily_metrics_compute_lambda.py")).read()
    build = src.index("_sick_item = {")
    carry = src.index("carry_coowned_fields(table, _sick_item)")
    put = src.index("table.put_item(Item=_sick_item)")
    assert build < carry < put


# ──────────────────────────────────────────────────────────────────────────────
# 2. The derivation guard — the acwr writer and the registry cannot drift
# ──────────────────────────────────────────────────────────────────────────────


def test_acwr_writer_field_set_matches_the_registry():
    src = open(os.path.join(_REPO, "lambdas", "compute", "acwr_compute_lambda.py")).read()
    # Unconditional SET parts: 'field = :placeholder' strings inside set_parts.
    written = set(re.findall(r'"(\w+)\s+=\s+:\w+"', src))
    # Conditional value fields: set_parts.append("field = :ph")
    written |= set(re.findall(r'set_parts\.append\("(\w+)\s*=\s*:\w+"\)', src))
    assert written == set(ACWR_COOWNED_FIELDS), (
        "acwr-compute writes a different field set than the co-owned registry — "
        f"only in writer: {sorted(written - set(ACWR_COOWNED_FIELDS))}, "
        f"only in registry: {sorted(set(ACWR_COOWNED_FIELDS) - written)}. "
        "Update compute.computed_metrics_contract.ACWR_COOWNED_FIELDS with the writer, "
        "or the preservation in store_computed_metrics silently loses the new field."
    )


# ──────────────────────────────────────────────────────────────────────────────
# 3. The dead-man — qa_smoke acwr_liveness
# ──────────────────────────────────────────────────────────────────────────────


def _qa():
    from operational import qa_smoke_lambda as qa

    return qa


class _QaTable:
    def __init__(self, records):
        self.records = records  # sk → item

    def get_item(self, Key=None, **kwargs):
        item = self.records.get(Key["sk"])
        return {"Item": item} if item else {}


def _run_liveness(monkeypatch, records):
    qa = _qa()
    from operational import acwr_liveness_qa

    (check,) = acwr_liveness_qa.check_acwr_liveness(_QaTable(records), qa.USER_PREFIX, qa.Check, qa.CONTENT_TRUTH, qa.pt_now)
    return check


def test_deadman_green_on_a_fresh_merge(monkeypatch):
    qa = _qa()
    yesterday = (qa.pt_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    fresh = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    check = _run_liveness(monkeypatch, {"DATE#" + yesterday: {"acwr_computed_at": fresh}})
    assert check.passed is True


def test_deadman_red_past_the_age_bar(monkeypatch):
    qa = _qa()
    yesterday = (qa.pt_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    stale = (datetime.now(timezone.utc) - timedelta(hours=ACWR_MAX_AGE_HOURS + 1)).isoformat()
    check = _run_liveness(monkeypatch, {"DATE#" + yesterday: {"acwr_computed_at": stale}})
    assert check.passed is False


def test_deadman_red_on_total_absence(monkeypatch):
    """The incident's exact observable: records exist, acwr fields do not."""
    qa = _qa()
    yesterday = (qa.pt_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    check = _run_liveness(monkeypatch, {"DATE#" + yesterday: {"day_grade_letter": "F"}})
    assert check.passed is False


def test_deadman_is_wired_into_the_nightly():
    qa = _qa()
    labels = [label for label, _fn in qa.check_steps()]
    assert "acwr_liveness" in labels
