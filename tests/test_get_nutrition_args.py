"""
Reproduce the get_nutrition positional args bug.
Test that all view dispatches work with various argument combinations.
"""
import os
import pytest

# Set required env vars before importing MCP modules
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("S3_REGION", "us-west-2")

from mcp.tools_nutrition import tool_get_nutrition


def test_nutrition_no_args():
    """Default view with no arguments should not crash."""
    result = tool_get_nutrition({})
    assert isinstance(result, dict)


def test_nutrition_summary_view():
    result = tool_get_nutrition({"view": "summary"})
    assert isinstance(result, dict)


def test_nutrition_macros_view():
    result = tool_get_nutrition({"view": "macros"})
    assert isinstance(result, dict)


def test_nutrition_meal_timing_view():
    result = tool_get_nutrition({"view": "meal_timing"})
    assert isinstance(result, dict)


def test_nutrition_micronutrients_view():
    result = tool_get_nutrition({"view": "micronutrients"})
    assert isinstance(result, dict)


def test_nutrition_with_dates():
    result = tool_get_nutrition({
        "view": "summary",
        "start_date": "2026-03-01",
        "end_date": "2026-03-31"
    })
    assert isinstance(result, dict)


def test_nutrition_macros_with_overrides():
    result = tool_get_nutrition({
        "view": "macros",
        "calorie_target": 2200,
        "protein_target": 200,
        "days": 14
    })
    assert isinstance(result, dict)


def test_nutrition_invalid_view():
    result = tool_get_nutrition({"view": "invalid"})
    assert "error" in result
