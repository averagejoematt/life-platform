"""tests/test_classify_core.py — B2b (2026-06-21).

classify_exercise mapped only direct flexion/oblique work to Core, so anti-rotation
presses (Pallof) and loaded carries (farmer/suitcase) fell through to "Other" and
core_sets read 0 on a day they were trained. These tests lock the anti-rotation /
carry family onto Core while proving the big-three patterns are untouched. Pure
functions — no AWS, no network (env vars set only so mcp.config imports cleanly).
"""

import os

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")

from mcp.strength_helpers import classify_exercise  # noqa: E402


def _pattern(name):
    return classify_exercise(name)["movement_pattern"]


def _muscles(name):
    return classify_exercise(name)["muscle_groups"]


def test_anti_rotation_and_carries_map_to_core():
    for name in [
        "Pallof Press",
        "Cable Pallof",
        "Farmer's Carry",
        "Farmer Walk",
        "Suitcase Carry",
        "Dead Bug",
        "Bird Dog",
        "Ab Wheel Rollout",
        "Cable Woodchop",
        "Hanging Knee Raise",
        "Russian Twist",
    ]:
        assert _pattern(name) == "Core", f"{name} should be Core, got {_pattern(name)}"
        assert "Core" in _muscles(name), f"{name} muscles={_muscles(name)}"


def test_existing_core_still_core():
    for name in ["Cable Crunch", "Plank", "Hanging Leg Raise", "Decline Sit Up"]:
        assert _pattern(name) == "Core"


def test_big_three_patterns_untouched():
    # The carry/anti-rotation keywords must not poach the major patterns.
    assert _pattern("Barbell Bench Press") == "Push"
    assert _pattern("Conventional Deadlift") == "Pull"  # NOT Core via "dead bug"
    assert _pattern("Back Squat") == "Legs"
    assert _pattern("Barbell Row") == "Pull"
    # "Dead Bug" must not be swept into the deadlift (Pull) bucket.
    assert _pattern("Dead Bug") == "Core"
