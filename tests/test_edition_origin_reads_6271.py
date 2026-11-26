"""tests/test_edition_origin_reads_6271.py — two /api/edition upstreams read only what they use (#6271).

Measured 2026-11-26 (local read-only replay against the live table): an uncached /api/edition parsed 6.9 MB of DynamoDB
JSON, and 2.3 MB of it was whole Apple Health day rows. ``pulse_history`` read every day since genesis for steps and
active energy, and ``journey`` read a week of them for one weight. Both reads now project. This file pins that each
projection carries every attribute its reader takes off a row. A field read but not projected would silently become
None live, so the fakes here return only the projected attributes, the way DynamoDB does.

Synthetic rows only.
"""

from __future__ import annotations

import inspect
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _k, _v in {"TABLE_NAME": "life-platform", "S3_BUCKET": "matthew-life-platform", "AWS_REGION": "us-west-2"}.items():
    os.environ.setdefault(_k, _v)
if os.path.join(ROOT, "lambdas") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from common import metric_truth  # noqa: E402
from health import weight_trend  # noqa: E402
from web import site_api_journey as journey, site_api_pulse as pulse  # noqa: E402


def _projected(rows, projection):
    keep = None if projection is None else {"sk", "tombstone", *projection}
    return [r if keep is None else {k: v for k, v in r.items() if k in keep} for r in rows]


def _gets(fn) -> set:
    """Every literal attribute ``fn`` reads with ``item.get("x")`` / ``r.get("x")``."""
    return set(re.findall(r"""\b(?:item|r|row)\.get\(\s*["']([A-Za-z_]+)["']""", inspect.getsource(fn)))


def test_the_journey_weight_projection_carries_every_field_latest_weight_reads():
    read = _gets(weight_trend._record_date) | _gets(weight_trend._record_weight_lbs)
    assert read, "the source scan found nothing: re-check _gets against weight_trend"
    assert read <= {"sk", *journey._AH_WEIGHT_PROJECTION}, read - {"sk", *journey._AH_WEIGHT_PROJECTION}
    rows = [
        {"sk": "DATE#2026-12-01", "date": "2026-12-01", "weight_kg": 130.0, "steps": 9000, "heart_rate": [1, 2, 3]},
        {"sk": "DATE#2026-12-02", "date": "2026-12-02", "weight_lbs": 287.4, "active_calories": 500},
        {"sk": "DATE#2026-12-03", "date": "2026-12-03", "steps": 4000},
    ]
    assert weight_trend.latest_weight([], _projected(rows, journey._AH_WEIGHT_PROJECTION)) == weight_trend.latest_weight([], rows)


def test_the_pulse_step_sources_project_the_resolvers_fields_and_active_energy():
    asked = {}

    def q(source, start, end, include_pilot=False, projection=None):
        asked[source] = projection
        return []

    pulse.pulse_history(_g={"EXPERIMENT_START": "2026-12-01", "_get_profile": lambda: {}, "_query_source": q})
    fields = metric_truth.metric_truth("steps")["field_by_source"]
    assert asked["apple_health"] == ("date", fields["apple_health"], pulse._ACTIVE_KCAL_FIELD)
    assert asked["garmin"] == ("date", fields["garmin"])
    assert asked["whoop"] is None and asked["withings"] is None, "the rows read whole stay whole"
    assert _gets(pulse._watch_active_kcal_by_date) <= {"sk", "date", pulse._ACTIVE_KCAL_FIELD}
