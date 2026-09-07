"""#3666 — the habit/instrument cross-source contract, the check that was missing.

Sixteen stored days were wrong and nothing noticed, because every habit assertion in the
tree asked whether a RECORD existed or whether its SHAPE was valid. None asked whether
its content agreed with an instrument that measured the same behaviour — and only a
cross-SOURCE question can, since a same-source check is satisfied by the very bug that
produced the data.

Both legs were violated live on 2026-09-06, and both real rows are replayed below:

    withings    DATE#2026-09-06  weight_lbs 327.34        habitify "Weigh In"      failed
    macrofactor DATE#2026-09-06  entries_count 10         habitify "Food Journal"  failed

Run:  python3 -m pytest tests/test_habit_cross_source_contract_3666.py -v
"""

import os
import sys
from datetime import datetime, timedelta
from decimal import Decimal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from operational.habit_cross_source_qa import (  # noqa: E402
    CROSS_SOURCE_CONTRACTS,
    check_habit_cross_source,
    cross_source_violations,
    has_evidence,
)

DAY = "2026-09-06"

# The live rows, field-for-field (values verbatim from DynamoDB on 2026-09-06).
WITHINGS_0906 = {"date": DAY, "weight_lbs": Decimal("327.34"), "weight_kg": Decimal("148.478")}
MACROFACTOR_0906 = {"date": DAY, "entries_count": Decimal("10"), "total_meals": Decimal("4"), "total_calories_kcal": Decimal("2410")}
EVIDENCE_0906 = {"withings": True, "macrofactor": True}

BROKEN_STATUSES = {  # what habitify actually stored for DATE#2026-09-06
    "Weigh In": {"status": "failed", "group": "Core"},
    "Food Journal": {"status": "failed", "group": "Core"},
}
FIXED_STATUSES = {  # what #3666's attribution rule stores for the same day
    "Weigh In": {"status": "completed", "group": "Core", "completed_at": "2026-09-07T02:11:22.363Z"},
    "Food Journal": {"status": "completed", "group": "Core", "completed_at": "2026-09-07T02:13:16.384Z"},
}


class _FakeTable:
    def __init__(self, items):
        self._items = items

    def get_item(self, Key):  # noqa: N803 — boto3's own kwarg name
        item = self._items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}


class _Check:
    """The minimum of operational.qa_check.Check this module touches."""

    def __init__(self, name, category, partition):
        self.name, self.category, self.partition = name, category, partition
        self.passed, self.message = None, ""

    def ok(self, msg=""):
        self.passed, self.message = True, msg
        return self

    def fail(self, msg=""):
        self.passed, self.message = False, msg
        return self

    def warn(self, msg="", chronic=False):
        self.passed, self.message = None, msg
        return self


def _pt_now():
    return datetime.fromisoformat("2026-09-07T09:00:00")


def _table(habitify_statuses, withings=WITHINGS_0906, macrofactor=MACROFACTOR_0906):
    return _FakeTable(
        {
            ("USER#matthew#SOURCE#habitify", "DATE#" + DAY): {"habit_statuses": habitify_statuses},
            ("USER#matthew#SOURCE#withings", "DATE#" + DAY): withings,
            ("USER#matthew#SOURCE#macrofactor", "DATE#" + DAY): macrofactor,
        }
    )


# ── THE CONTRACT ─────────────────────────────────────────────────────────────────────


def test_the_live_2026_09_06_rows_violate_the_contract():
    """The whole point: this is a RED on the day the platform reported green."""
    violations = cross_source_violations(DAY, BROKEN_STATUSES, EVIDENCE_0906)
    assert len(violations) == 2
    assert any("Weigh In" in v and "withings" in v for v in violations)
    assert any("Food Journal" in v and "macrofactor" in v for v in violations)


def test_the_post_fix_day_satisfies_the_contract():
    assert cross_source_violations(DAY, FIXED_STATUSES, EVIDENCE_0906) == []


def test_pending_with_evidence_is_not_a_violation():
    """An open Pacific day legitimately holds `pending` — #3666 restored exactly that,
    and a check that red on it would undo the fix it exists to protect."""
    statuses = {"Weigh In": {"status": "pending"}, "Food Journal": {"status": "pending"}}
    assert cross_source_violations(DAY, statuses, EVIDENCE_0906) == []


def test_completed_without_evidence_is_not_a_violation():
    """Deliberately one-directional. He can step on the scale with the app closed, and
    MacroFactor is ~24h behind by design — asserting this direction would red on the
    partner's latency rather than on truth."""
    assert cross_source_violations(DAY, FIXED_STATUSES, {"withings": False, "macrofactor": False}) == []


def test_failed_without_evidence_is_not_a_violation():
    """A genuinely missed day must stay a quiet, honest `failed`."""
    assert cross_source_violations(DAY, BROKEN_STATUSES, {"withings": False, "macrofactor": False}) == []


def test_each_contract_is_independently_load_bearing():
    """Guard the SET, not one instance: dropping either pair must change the verdict."""
    for contract in CROSS_SOURCE_CONTRACTS:
        only_this = {contract["source"]: True}
        violations = cross_source_violations(DAY, BROKEN_STATUSES, only_this)
        assert len(violations) == 1, f"{contract['habit']} is not independently checked"
        assert contract["habit"] in violations[0]


def test_a_new_contract_needs_no_change_here_but_cannot_be_silently_empty():
    assert len(CROSS_SOURCE_CONTRACTS) >= 2
    assert {c["source"] for c in CROSS_SOURCE_CONTRACTS} == {"withings", "macrofactor"}


# ── EVIDENCE ─────────────────────────────────────────────────────────────────────────


def test_an_empty_partner_record_is_not_evidence():
    """An absence marker or a zeroed row must not manufacture a violation."""
    assert has_evidence({"date": DAY}, ("weight_lbs", "weight_kg")) is False
    assert has_evidence({"date": DAY, "absent": True}, ("weight_lbs",)) is False
    assert has_evidence({"weight_lbs": Decimal("0")}, ("weight_lbs",)) is False
    assert has_evidence(None, ("weight_lbs",)) is False


def test_a_real_partner_record_is_evidence():
    assert has_evidence(WITHINGS_0906, ("weight_lbs", "weight_kg")) is True
    assert has_evidence(MACROFACTOR_0906, ("entries_count", "total_meals")) is True


def test_a_non_numeric_field_never_raises():
    assert has_evidence({"weight_lbs": "heavy"}, ("weight_lbs",)) is False
    assert has_evidence({"weight_lbs": True}, ("weight_lbs",)) is False


# ── THE NIGHTLY LEG ──────────────────────────────────────────────────────────────────


def test_the_nightly_check_reds_on_the_live_broken_day():
    (check,) = check_habit_cross_source(_table(BROKEN_STATUSES), "USER#matthew#SOURCE#", _Check, "content_truth", _pt_now)
    assert check.passed is False
    assert "Weigh In" in check.message and "Food Journal" in check.message


def test_the_nightly_check_greens_on_the_fixed_day():
    (check,) = check_habit_cross_source(_table(FIXED_STATUSES), "USER#matthew#SOURCE#", _Check, "content_truth", _pt_now)
    assert check.passed is True


def test_the_nightly_check_measures_the_last_CLOSED_pacific_day():
    """Yesterday, not today: a day still open holds `pending` by design."""
    seen = []

    class _Spy(_FakeTable):
        def get_item(self, Key):  # noqa: N803
            seen.append(Key["sk"])
            return super().get_item(Key)

    spy = _Spy(_table(FIXED_STATUSES)._items)
    check_habit_cross_source(spy, "USER#matthew#SOURCE#", _Check, "content_truth", _pt_now)
    expected = "DATE#" + (_pt_now() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert set(seen) == {expected}


def test_a_missing_habit_record_warns_rather_than_reporting_an_unearned_green():
    (check,) = check_habit_cross_source(_table({}), "USER#matthew#SOURCE#", _Check, "content_truth", _pt_now)
    assert check.passed is None
    assert "not evaluable" in check.message


def test_a_ddb_error_reds_rather_than_disappearing():
    class _Broken:
        def get_item(self, Key):  # noqa: N803
            raise RuntimeError("throughput exceeded")

    (check,) = check_habit_cross_source(_Broken(), "USER#matthew#SOURCE#", _Check, "content_truth", _pt_now)
    assert check.passed is False
    assert "DDB error" in check.message


def test_the_check_is_wired_into_the_nightly_sweep():
    """A check nobody registered never runs (#1917's rule, and #3666's own class)."""
    src = open(os.path.join(ROOT, "lambdas", "operational", "qa_smoke_lambda.py"), encoding="utf-8").read()
    assert "habit_cross_source_qa" in src
    assert '"habit_cross_source"' in src
