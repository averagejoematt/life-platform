"""tests/test_coach_panel_podcast.py — CC podcast "The Panel" guardrails (offline).

PG-10 budget self-skip, ER-03 line gating + speaker→persona mapping, and the
rotating co-host fallback — all without AWS/Bedrock/TTS.
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import budget_guard  # noqa: E402
import persona_registry  # noqa: E402
from emails import coach_panel_podcast_lambda as panel  # noqa: E402


def test_self_skips_at_tier_2(monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    out = panel.lambda_handler({}, None)
    assert out == {"skipped": True, "tier": 2}


def test_gate_turns_maps_speakers_and_drops_unsafe():
    turns = [
        {"speaker": "elena", "line": "So far the trend looks early and gentle."},  # clean
        {"speaker": "coach", "line": "Sleep improved because you trained harder."},  # causal -> drop
        {"speaker": "coach", "line": "Recovery sits around 7, an early signal."},  # 7 allowed + hedge -> keep
        {"speaker": "coach", "line": "It jumped to 42 overnight."},  # fabricated number -> drop
    ]
    clean = panel._gate_turns(turns, allowed_numbers={7}, coach_id="sleep_coach")
    assert [t["speaker"] for t in clean] == ["elena_voss", "sleep_coach"]
    assert "because" not in " ".join(t["line"] for t in clean)
    assert all("42" not in t["line"] for t in clean)


def test_pick_coach_fallback_is_operational(monkeypatch):
    # offline: _coach_latest returns None for all -> round-robin fallback
    monkeypatch.setattr(panel, "_coach_latest", lambda cid: None)
    cid, out = panel._pick_coach(3)
    assert cid in persona_registry.OPERATIONAL_COACH_IDS and out is None
    assert cid == persona_registry.OPERATIONAL_COACH_IDS[3 % 8]


def test_intro_gate_resolves_any_speaker_and_drops_unsafe():
    turns = [
        {"speaker": "elena", "line": "Welcome — we're just getting started."},  # -> elena_voss
        {"speaker": "training_coach", "line": "I'm here for the early movement trend."},  # coach id kept
        {"speaker": "Dr. Lisa Park", "line": "Sleep is where it begins, early days."},  # display name -> sleep_coach
        {"speaker": "training_coach", "line": "You lost it because you skipped sleep."},  # causal -> drop
        {"speaker": "nobody", "line": "ghost"},  # unknown speaker -> drop
    ]
    speakers = [t["speaker"] for t in panel._gate_intro(turns, allowed_numbers=set())]
    assert speakers == ["elena_voss", "training_coach", "sleep_coach"]


def test_voice_routing_returns_chirp_voice():
    # Tolerant of S3-vs-local registry state: every speaker resolves to a real
    # Chirp 3: HD voice (the mapped one once personas.json is synced, else a
    # Chirp fallback — never empty/Polly).
    for spk in ("elena_voss", "training_coach", "labs_coach"):
        v = panel._voice(spk)
        assert v and v.startswith("en-US-Chirp3-HD-")
