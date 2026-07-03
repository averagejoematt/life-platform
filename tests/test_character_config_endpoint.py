"""
/api/character_config — the character sheet's "how the engine works" contract
(P1.2). The handler serves a WHITELISTED subset of the MCP-editable engine
config; these tests pin the whitelist so a config field can never leak by
accident (fail-closed privacy, same discipline as /api/presence).

All offline — the S3 read is monkeypatched.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import site_api_vitals as vitals  # noqa: E402


def _cfg():
    return {
        "_meta": {"version": "1.1.1", "last_updated": "2026-05-18", "notes": "internal"},
        "baseline": {"start_date": "2026-06-14", "start_weight_lbs": 314.52, "goal_weight_lbs": 185},
        "pillars": {
            "sleep": {
                "weight": 0.20,
                "ema_lambda": 0.85,
                "owner": "Dr. Real Person",
                "components": {
                    "duration_vs_target": {"weight": 0.25, "target_hours": 7.5},
                    "efficiency": {"weight": 0.2, "_internal": {"x": 1}},
                },
            },
            "nutrition": {
                "weight": 0.18,
                "ema_lambda": 0.9,
                "owner": "Dr. Peter Attia",
                "components": {"protein_total": {"weight": 0.2, "target_grams": 190}},
            },
        },
        "leveling": {
            "ema_lambda": 0.85,
            "ema_window_days": 21,
            "level_up_streak_days": 5,
            "level_down_streak_days": 7,
            "tier_up_streak_days": 7,
            "tier_down_streak_days": 10,
            "level_step_threshold": 10,
            "xp_per_level": 100,
            "daily_xp_decay": 2,
            "xp_buffer_threshold": 20,
            "tier_streak_overrides": {"Foundation": {"up": 3, "down": 5}},
            "secret_internal_knob": "never-serve",
        },
        "xp_bands": [{"min_raw_score": 80, "xp": 3}, {"min_raw_score": 0, "xp": -1}],
        "tiers": [{"name": "Foundation", "emoji": "X", "min_level": 1, "max_level": 20}],
        "cross_pillar_effects": [
            {
                "name": "Sleep Drag",
                "emoji": "X",
                "condition": "sleep < 35",
                "targets": {"movement": {"type": "multiplicative", "value": -0.08}},
            }
        ],
        "avatar": {"enabled": True, "style": "pixel_rpg", "s3_prefix": "dashboard/avatar/"},
        "protocols": {"sleep": {"Foundation": ["private coach prescription text"]}},
    }


class _FakeS3:
    def __init__(self, payload):
        self._payload = payload

    def get_object(self, Bucket, Key):
        import io

        assert Key.endswith("character_sheet.json")
        return {"Body": io.BytesIO(json.dumps(self._payload).encode())}


def _serve(monkeypatch, payload):
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeS3(payload))
    resp = vitals.handle_character_config()
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])


def test_serves_mechanics(monkeypatch):
    body = _serve(monkeypatch, _cfg())
    assert body["available"] is True
    assert body["pillars"]["sleep"]["weight"] == 0.20
    assert body["pillars"]["sleep"]["components"]["duration_vs_target"]["target_hours"] == 7.5
    assert body["leveling"]["xp_per_level"] == 100
    assert body["leveling"]["tier_streak_overrides"]["Foundation"]["up"] == 3
    assert body["xp_bands"][0]["xp"] == 3
    assert body["tiers"] == [{"name": "Foundation", "min_level": 1, "max_level": 20}]
    assert body["cross_pillar_effects"][0]["condition"] == "sleep < 35"
    assert body["updated_at"] == "2026-05-18"


def test_whitelist_excludes_private_fields(monkeypatch):
    """The teeth: owner (real names), baseline, avatar, protocols, _meta internals,
    unknown leveling knobs, non-scalar component internals — none may serve."""
    body = _serve(monkeypatch, _cfg())
    text = json.dumps(body)
    assert "owner" not in text
    assert "Attia" not in text and "Real Person" not in text
    assert "baseline" not in body and "314.52" not in text
    assert "avatar" not in body and "pixel_rpg" not in text
    assert "protocols" not in body and "prescription" not in text
    assert "secret_internal_knob" not in text
    assert "_internal" not in text
    assert "notes" not in text  # _meta internals


def test_no_emoji_served(monkeypatch):
    """§8: tiers/effects emoji are stripped server-side."""
    body = _serve(monkeypatch, _cfg())
    assert "emoji" not in json.dumps(body)


def test_config_load_failure_is_honest_200(monkeypatch):
    import boto3

    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(boto3, "client", _boom)
    resp = vitals.handle_character_config()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["available"] is False
