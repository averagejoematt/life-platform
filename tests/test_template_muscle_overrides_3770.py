"""tests/test_template_muscle_overrides_3770.py — #3770: the id-keyed muscle-group
override for the corrupted Hevy "Calf Press on Leg Press Machine" template.

Fixture is the wire shape: a Hevy workout exercise row exactly as
`normalize_hevy_items` hands it to a classifier (`name` + `template_id`), not a
hand-built dict of muscle-group labels. Before the override the exercise's own
NAME would misclassify anyway (it contains "leg press" before it ever reaches
"calf" in the keyword map) — pinning that the id override wins regardless of what
the name alone would say is the whole point of checking the id FIRST.
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from training.template_muscle_overrides import (  # noqa: E402
    RETIRED_TEMPLATE_IDS,
    TEMPLATE_MUSCLE_OVERRIDES,
    is_retired_template,
    muscle_override_for,
)

from mcp.strength_helpers import classify_exercise  # noqa: E402

OLD_ID = "70b39605-52c0-4b79-855c-e26ea10440da"
CALF_PRESS_NAME = "Calf Press on Leg Press Machine"


# ── the override table itself ─────────────────────────────────────────────────


def test_old_template_id_is_registered_and_retired():
    assert TEMPLATE_MUSCLE_OVERRIDES[OLD_ID] == "Calves"
    assert OLD_ID in RETIRED_TEMPLATE_IDS


def test_muscle_override_for_is_case_and_whitespace_insensitive():
    assert muscle_override_for(OLD_ID) == "Calves"
    assert muscle_override_for(OLD_ID.upper()) == "Calves"
    assert muscle_override_for(f"  {OLD_ID}  ") == "Calves"


def test_muscle_override_for_absent_id_is_none():
    assert muscle_override_for(None) is None
    assert muscle_override_for("") is None
    assert muscle_override_for("some-other-template-id") is None


def test_is_retired_template():
    assert is_retired_template(OLD_ID) is True
    assert is_retired_template(OLD_ID.upper()) is True
    assert is_retired_template(None) is False
    assert is_retired_template("some-other-template-id") is False


# ── the classifier applying the override (feeds get_muscle_volume) ────────────


def test_a_session_against_the_old_id_classifies_as_calves():
    """Before: a set logged against OLD_ID with this name would classify as Quads/
    Glutes/Hamstrings (the "leg press" keyword fires before "calf" in the name map —
    proven by the mutation control below). After: the id override wins."""
    cls = classify_exercise(CALF_PRESS_NAME, OLD_ID)
    assert cls["muscle_groups"] == ["Calves"]
    assert cls["movement_pattern"] == "Legs"


def test_mutation_control_name_alone_does_not_say_calves():
    """Proves the override — not the name — is what decides the outcome for OLD_ID.

    #4071 fixed the name collision itself ("calf" now sits above "leg press" in
    `training.muscle_volume.EXERCISE_TAXONOMY`), so CALF_PRESS_NAME alone now reads Calves
    too. The control therefore uses a name that classifies as something else: the same id
    under a plain "Leg Press" title reads Quads by name and Calves by id."""
    assert "Calves" not in classify_exercise("Leg Press")["muscle_groups"]
    assert classify_exercise("Leg Press", OLD_ID)["muscle_groups"] == ["Calves"]


def test_the_name_collision_itself_is_fixed_4071():
    """#4071: the calf row sits above the leg-press row, so the title alone is Calves now."""
    assert classify_exercise(CALF_PRESS_NAME)["muscle_groups"] == ["Calves"]


def test_mutation_control_empty_override_table_falls_back_to_name(monkeypatch):
    """Empty the override and confirm classification falls all the way back to the name —
    pins that the override check is the ONLY thing turning a "Leg Press"-titled OLD_ID into
    Calves. Patched where the ONE attribution function (#4071) reads it."""
    import training.muscle_volume as mv

    monkeypatch.setattr(mv, "muscle_override_for", lambda template_id: None)
    cls = classify_exercise("Leg Press", OLD_ID)
    assert "Calves" not in cls["muscle_groups"]


def test_an_unrelated_template_id_is_unaffected():
    cls = classify_exercise("Standing Calf Raise", "some-other-template-id")
    assert cls["muscle_groups"] == ["Calves"]  # resolves via the ordinary name keyword


def test_a_true_shoulder_exercise_is_unaffected_by_the_override():
    cls = classify_exercise("Overhead Press", "some-other-template-id")
    assert cls["muscle_groups"] == ["Shoulders", "Triceps"]  # primary + the named 0.5 secondary (#4071)
