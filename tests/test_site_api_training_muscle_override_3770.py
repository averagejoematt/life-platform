"""tests/test_site_api_training_muscle_override_3770.py — #3770's id override still applies
on the public `/api/training_overview` path.

Before #4095, `web.site_api_training._compute_muscle_volume` carried its OWN duplicate
name-keyword map (`_MUSCLE_MAP`/`_classify_muscles`) — a second per-muscle set computation
outside the #4071 derivation guard's scope, which double-credited multi-muscle rows exactly
like the pre-#4071 MCP path did. #4095 deleted that duplicate and made
`_compute_muscle_volume` delegate to `training.muscle_volume.working_sets_by_muscle`, the
ONE per-muscle computation — this file now exercises the id override (#3770) THROUGH that
delegated path, not a second copy of it.

Fixture is the live per-workout Hevy DDB shape (`sk` carries `#WORKOUT#`, sets carry `type`
+ `weight_kg`, as the ingester writes them) — the shape `normalize_hevy_items` (now in
`training/muscle_volume.py`, #4095) actually reads.
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from web.site_api_training import _compute_muscle_volume  # noqa: E402

OLD_ID = "70b39605-52c0-4b79-855c-e26ea10440da"
CALF_PRESS_NAME = "Calf Press on Leg Press Machine"


def _workout(name, template_id, n_sets=3, date="2026-09-10", uid="t1"):
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{date}#WORKOUT#{uid}",
        "date": date,
        "exercises": [
            {
                "name": name,
                "template_id": template_id,
                "sets": [{"type": "normal", "weight_kg": 90, "reps": 12} for _ in range(n_sets)],
            }
        ],
    }


def test_compute_muscle_volume_counts_the_old_id_as_calves():
    hevy_items = [_workout(CALF_PRESS_NAME, OLD_ID, n_sets=4)]
    out = _compute_muscle_volume(hevy_items, num_weeks=1)
    muscles = {row["muscle"]: row for row in out}
    assert "Calves" in muscles
    assert muscles["Calves"]["total_sets"] == 4
    assert "Quads" not in muscles


def test_mutation_control_the_override_table_is_actually_consulted(monkeypatch):
    """Changing the override's target through the site path must change the answer — proves
    #3770's id override is read on THIS path, not silently satisfied by a name match alone."""
    import training.template_muscle_overrides as tmo

    monkeypatch.setitem(tmo.TEMPLATE_MUSCLE_OVERRIDES, OLD_ID, "Shoulders")
    hevy_items = [_workout(CALF_PRESS_NAME, OLD_ID, n_sets=4)]
    out = _compute_muscle_volume(hevy_items, num_weeks=1)
    muscles = {row["muscle"] for row in out}
    assert "Shoulders" in muscles
    assert "Calves" not in muscles


def test_no_override_still_classifies_by_name_via_the_taxonomy():
    """With no template_id at all, the shared taxonomy (not a site-local keyword table)
    classifies the exercise by name — "calf" matches ahead of "leg press" (#4071's
    word-boundary, most-specific-first ordering), so no override is even needed here."""
    hevy_items = [_workout(CALF_PRESS_NAME, template_id="", n_sets=4)]
    out = _compute_muscle_volume(hevy_items, num_weeks=1)
    muscles = {row["muscle"] for row in out}
    assert "Calves" in muscles
    assert "Quads" not in muscles
