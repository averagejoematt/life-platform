"""tests/test_site_api_training_muscle_override_3770.py — #3770's id override applied
to the SECOND muscle-volume aggregation (`training_overview`'s `_compute_muscle_volume`),
which duplicates `mcp/tools_strength.py`'s name-keyword map and carries the exact same
"leg press" fires before "calf" ordering hazard.

Fixture is the wire shape `_compute_muscle_volume` actually reads: a day-level Hevy DDB
item with an `exercises` list, each carrying `name` + `template_id` (the fields
`normalize_hevy_items` also uses elsewhere in this codebase for the same partition).
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from web.site_api_training import _classify_muscles, _compute_muscle_volume  # noqa: E402

OLD_ID = "70b39605-52c0-4b79-855c-e26ea10440da"
CALF_PRESS_NAME = "Calf Press on Leg Press Machine"


def _workout_day(name, template_id, n_sets=3):
    return {
        "date": "2026-09-10",
        "exercises": [
            {
                "name": name,
                "template_id": template_id,
                "sets": [{"type": "normal", "weight_lbs": 200, "reps": 12} for _ in range(n_sets)],
            }
        ],
    }


def test_classify_muscles_applies_the_override():
    assert _classify_muscles(CALF_PRESS_NAME, OLD_ID) == ["Calves"]


def test_mutation_control_name_alone_hits_leg_press_not_calf():
    assert _classify_muscles(CALF_PRESS_NAME) == ["Quads", "Glutes", "Hamstrings"]


def test_compute_muscle_volume_counts_the_old_id_as_calves():
    hevy_items = [_workout_day(CALF_PRESS_NAME, OLD_ID, n_sets=4)]
    out = _compute_muscle_volume(hevy_items, num_weeks=1)
    muscles = {row["muscle"]: row for row in out}
    assert "Calves" in muscles
    assert muscles["Calves"]["total_sets"] == 4
    assert "Quads" not in muscles


def test_mutation_control_empty_override_table_regresses_to_leg_press(monkeypatch):
    import web.site_api_training as sat

    monkeypatch.setattr(sat, "muscle_override_for", lambda template_id: None)
    hevy_items = [_workout_day(CALF_PRESS_NAME, OLD_ID, n_sets=4)]
    out = _compute_muscle_volume(hevy_items, num_weeks=1)
    muscles = {row["muscle"] for row in out}
    assert "Calves" not in muscles
    assert "Quads" in muscles
