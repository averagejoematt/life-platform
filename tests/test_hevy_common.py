"""Unit tests for hevy_common.normalize_workout — schema mapping + unit handling.

These tests do NOT hit AWS or the Hevy API. They feed synthetic payloads
mirroring Hevy's documented response shape into the normalizer and assert
the resulting record satisfies the platform's schema contract.

Re-run the parity check in a separate `tests/test_hevy_live.py` when actual
payloads are available (left as a TODO so the live shape can be pinned).
"""
import os
import sys

import pytest

# Ensure lambdas/ is importable without setting boto3 environment first.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))


@pytest.fixture(autouse=True)
def _stub_aws(monkeypatch):
    """Stub the boto3 clients hevy_common creates at module load time."""
    import types
    fake_boto3 = types.ModuleType("boto3")

    class _FakeTable:
        def put_item(self, **kw): pass
        def get_item(self, **kw): return {}

    class _FakeDDBResource:
        def Table(self, name): return _FakeTable()

    def fake_client(name, region_name=None):
        return object()

    def fake_resource(name, region_name=None):
        return _FakeDDBResource()

    fake_boto3.client = fake_client
    fake_boto3.resource = fake_resource
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)


@pytest.fixture
def sample_workout_kg():
    return {
        "workout": {
            "id": "wkt_abc123",
            "title": "Push Day A",
            "description": "Bench focus",
            "start_time": "2026-05-25T17:30:00Z",
            "end_time":   "2026-05-25T18:25:00Z",
            "unit": "kg",
            "exercises": [
                {
                    "title": "Barbell Bench Press",
                    "exercise_template_id": "tpl_bench",
                    "sets": [
                        {"index": 0, "weight_kg": 60.0, "reps": 5, "type": "normal"},
                        {"index": 1, "weight_kg": 70.0, "reps": 5, "type": "normal"},
                        {"index": 2, "weight_kg": 80.0, "reps": 5, "type": "normal"},
                    ],
                    "notes": "Felt strong",
                },
                {
                    "title": "Dumbbell Row",
                    "exercise_template_id": "tpl_db_row",
                    "sets": [
                        {"index": 0, "weight_kg": 25.0, "reps": 10},
                        {"index": 1, "weight_kg": 25.0, "reps": 10},
                    ],
                },
            ],
        }
    }


@pytest.fixture
def sample_workout_lbs():
    return {
        "workout": {
            "id": "wkt_def456",
            "title": "Squat Day",
            "start_time": "2026-05-25T15:00:00Z",
            "end_time":   "2026-05-25T16:00:00Z",
            "unit": "lbs",
            "exercises": [
                {
                    "title": "Back Squat",
                    "sets": [
                        # Weight expressed as lbs (no _kg suffix) per the unit hint.
                        {"index": 0, "weight": 135.0, "reps": 5},
                        {"index": 1, "weight": 185.0, "reps": 5},
                    ],
                },
            ],
        }
    }


def test_normalize_workout_kg_pk_sk(sample_workout_kg):
    from hevy_common import normalize_workout
    rec = normalize_workout(sample_workout_kg)
    assert rec["pk"] == "USER#matthew#SOURCE#hevy"
    assert rec["sk"] == "DATE#2026-05-25#WORKOUT#wkt_abc123"
    assert rec["source"] == "hevy"
    assert rec["source_workout_id"] == "wkt_abc123"
    assert rec["workout_uid"] == "hevy:wkt_abc123"
    assert rec["date"] == "2026-05-25"


def test_normalize_workout_kg_volume(sample_workout_kg):
    """Total volume = sum(weight_kg * reps) across all sets."""
    from hevy_common import normalize_workout
    rec = normalize_workout(sample_workout_kg)
    expected = (60 * 5) + (70 * 5) + (80 * 5) + (25 * 10) + (25 * 10)
    assert rec["total_volume_kg"] == float(expected)
    assert rec["exercise_count"] == 2
    assert rec["set_count"] == 5


def test_normalize_workout_lbs_converts_to_kg(sample_workout_lbs):
    """When unit=lbs, all weights normalize to kg."""
    from hevy_common import normalize_workout
    rec = normalize_workout(sample_workout_lbs)
    assert rec["original_unit"] == "lbs"
    sets = rec["exercises"][0]["sets"]
    # 135 lbs → ~61.235 kg, 185 lbs → ~83.915 kg
    assert sets[0]["weight_kg"] == pytest.approx(61.235, abs=0.01)
    assert sets[1]["weight_kg"] == pytest.approx(83.915, abs=0.01)
    # Volume in kg should be sum(weight_kg * reps)
    expected = pytest.approx((61.235 + 83.915) * 5, abs=0.05)
    assert rec["total_volume_kg"] == expected


def test_normalize_workout_duration(sample_workout_kg):
    from hevy_common import normalize_workout
    rec = normalize_workout(sample_workout_kg)
    # 17:30 → 18:25 = 55 minutes = 3300s
    assert rec["duration_sec"] == 3300


def test_normalize_workout_raw_ref_points_at_s3(sample_workout_kg):
    from hevy_common import normalize_workout
    rec = normalize_workout(sample_workout_kg)
    assert rec["raw_ref"] == "s3://matthew-life-platform/raw/hevy/wkt_abc123.json"


def test_normalize_workout_missing_id_raises():
    from hevy_common import normalize_workout
    with pytest.raises(ValueError, match="missing workout id"):
        normalize_workout({"workout": {"title": "no id"}})


def test_normalize_workout_top_level_id_accepted():
    """Hevy may return the workout at top level (not wrapped in 'workout')."""
    from hevy_common import normalize_workout
    rec = normalize_workout({
        "id": "top_level_id",
        "title": "Flat",
        "start_time": "2026-05-25T10:00:00Z",
        "exercises": [],
    })
    assert rec["source_workout_id"] == "top_level_id"


# ── Webhook signature ────────────────────────────────────────────────────────

def test_verify_signature_direct_match(monkeypatch):
    """Direct-string-match path (Hevy's simplest auth mechanism)."""
    from hevy_common import verify_webhook_signature
    monkeypatch.setattr(
        "hevy_common.load_secret",
        lambda: {"api_key": "irrelevant", "webhook_secret": "shared-bearer-token-xyz"},
    )
    assert verify_webhook_signature(b"any body", "shared-bearer-token-xyz") is True
    assert verify_webhook_signature(b"any body", "wrong-secret") is False


def test_verify_signature_hmac_match(monkeypatch):
    """HMAC-SHA256 path."""
    import hashlib
    import hmac as _hmac
    from hevy_common import verify_webhook_signature
    monkeypatch.setattr(
        "hevy_common.load_secret",
        lambda: {"api_key": "irrelevant", "webhook_secret": "k"},
    )
    body = b'{"workoutId":"wkt_abc"}'
    sig = _hmac.new(b"k", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig) is True
    assert verify_webhook_signature(body, "sha256=" + sig) is True
    assert verify_webhook_signature(body, "nope") is False
