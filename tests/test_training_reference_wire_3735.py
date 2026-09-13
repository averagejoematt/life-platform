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


def test_the_schema_marker_is_stored_and_is_v2():
    """The specific field whose absence made the prescription view permanently wrong.
    Asserted as a VALUE, not just presence — a stored `reference_schema: 1` would read
    as an honest stale record and be just as wrong."""
    item = ed.build_training_reference_record(_reference())
    assert "reference_schema" in item, "the v1/v2 discriminator is not on the record at all"
    assert int(item["reference_schema"]) == 2, f"stored schema is {item['reference_schema']}, expected 2"


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
