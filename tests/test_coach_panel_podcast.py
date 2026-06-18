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


def test_intro_gate_resolves_two_speakers_and_drops_unsafe():
    # Episode 0 is a two-hander: Elena (host) + Eli (the PI guest). Only those two
    # resolve; coaches/unknowns drop; ER-03 still kills causal claims.
    turns = [
        {"speaker": "elena", "line": "Welcome — we're just getting started."},  # -> elena_voss
        {"speaker": "eli", "line": "Glad to be here. Early days, but it's promising."},  # -> eli_marsh
        {"speaker": "Dr. Eli Marsh", "line": "The data's a lead, not a verdict."},  # display name -> eli_marsh
        {"speaker": "eli", "line": "He lost the weight because he slept more."},  # causal -> drop
        {"speaker": "training_coach", "line": "I'm a coach, not in this episode."},  # not a valid intro speaker -> drop
    ]
    speakers = [t["speaker"] for t in panel._gate_intro(turns, allowed_numbers=set())]
    assert speakers == ["elena_voss", "eli_marsh", "eli_marsh"]


def test_safety_gate_fails_closed_on_every_banned_class():
    # The Personal Board's hard line: the autonomous weekly publisher must HOLD
    # (never voice) on any of these. Each must produce a violation reason.
    panel._content_filter_cache = {
        "blocked_vices": ["No porn", "No marijuana"],
        "blocked_vice_keywords": ["porn", "marijuana", "cannabis", "weed", "thc", "edibles"],
    }
    cases = {
        "blocked-vice": "He kept his no-marijuana streak going.",
        "body-number": "He's down to 305 pounds this week.",
        "grief/family/named-person": "It's been hard since my mother's diagnosis.",
        "report-card-tone": "Honestly, you should have trained more — not good enough.",
        "causal-claim": "The cold plunge caused his recovery to jump.",
    }
    for expected, text in cases.items():
        reasons = panel._safety_gate(text)
        assert any(expected.split("/")[0].split(":")[0] in r for r in reasons), f"{expected!r} not caught in {reasons} for {text!r}"
    # A clean, compassionate, process-focused line passes.
    assert panel._safety_gate("You showed up on the two days you said would be hardest — that's the work.") == []


def test_sensitivity_routing_holds_hard_weeks():
    # Personal Board asymmetry: a grief/low-mood week routes to a human (hold), not auto-publish.
    assert panel._sensitivity_hold_reasons({"chronicle": "This week was heavy — grief has a way of resurfacing."})
    assert panel._sensitivity_hold_reasons({"chronicle": "A relapse week; felt hopeless for a stretch."})
    assert panel._sensitivity_hold_reasons({"chronicle": "Solid week — three workouts, slept well, saw friends."}) == []


def test_weekly_gate_fails_closed_and_drops_unsafe():
    panel._content_filter_cache = {"blocked_vices": [], "blocked_vice_keywords": ["marijuana"]}
    turns = [
        {"speaker": "elena", "line": "Good week — you kept showing up, and that's the work."},  # clean → kept
        {"speaker": "coach", "line": "He's down to 305 pounds."},  # body number → HOLD
    ]
    clean, hold = panel._weekly_gate(turns, allowed_numbers=set(), guest_id="sleep_coach")
    assert hold, "a body-number line must trigger a hold reason"
    assert all("305 pounds" not in t["line"] for t in clean), "unsafe line must not survive into clean turns"


def test_gemini_voice_map_distinct():
    assert panel._gemini_voice("elena_voss") == "Aoede"
    assert panel._gemini_voice("sleep_coach") != panel._gemini_voice("elena_voss")
    assert panel._gemini_voice("unknown_coach")  # falls back to a real voice


def test_intro_hallucination_guard_drops_daycero_violations():
    # Episode 0 is Day Zero — the guard must drop fabricated elapsed time, results,
    # a starting weight, and references to a back-catalogue that doesn't exist.
    turns = [
        {"speaker": "elena", "line": "Welcome to the show — glad you're here."},  # keep
        {"speaker": "eli", "line": "We're two weeks into the experiment now."},  # elapsed time -> drop
        {"speaker": "eli", "line": "The numbers are showing real progress already."},  # results -> drop
        {"speaker": "elena", "line": "He started at 311 pounds, right?"},  # weight -> drop
        {"speaker": "eli", "line": "Last episode we dug into sleep."},  # back-catalogue -> drop
        {"speaker": "elena", "line": "This is the starting line — let's get into it."},  # keep
    ]
    out = panel._gate_intro(turns, allowed_numbers=set())
    assert [t["speaker"] for t in out] == ["elena_voss", "elena_voss"]
    assert all(not panel._HALLUCINATION_RE.search(t["line"]) for t in out)


def test_voice_routing_returns_chirp_voice():
    # Tolerant of S3-vs-local registry state: every speaker resolves to a real
    # Chirp 3: HD voice (the mapped one once personas.json is synced, else a
    # Chirp fallback — never empty/Polly).
    for spk in ("elena_voss", "training_coach", "labs_coach"):
        v = panel._voice(spk)
        assert v and v.startswith("en-US-Chirp3-HD-")


# ── QA rigor: deterministic craft gate (2026-06-17) ──────────────────────────


def test_craft_check_passes_clean_dialogue():
    turns = [
        {"speaker": "elena_voss", "line": "Here's the hook that got me."},
        {"speaker": "eli_marsh", "line": "Good place to start."},
        {"speaker": "elena_voss", "line": "So what is it, plainly?"},
        {"speaker": "eli_marsh", "line": "One life, fully in the open."},
    ]
    assert panel._craft_check(turns) == []


def test_craft_check_allows_three_but_flags_four_in_a_row():
    # Calibrated: 3 short turns reads fine; 4+ is the floor-hog that fails.
    three = [
        {"speaker": "elena_voss", "line": "One."},
        {"speaker": "eli_marsh", "line": "Two."},
        {"speaker": "eli_marsh", "line": "Three."},
        {"speaker": "eli_marsh", "line": "Four."},
    ]
    assert panel._craft_check(three) == []  # exactly 3 eli in a row — allowed
    four = three + [{"speaker": "eli_marsh", "line": "Five."}]
    fails = panel._craft_check(four)
    assert fails and "in a row" in fails[0]


def test_craft_check_flags_monologue_but_exempts_hook():
    long_line = "word " * (panel._QA_MAX_WORDS_PER_TURN + 5)
    # A long turn mid-conversation (not turn 0) → flagged.
    mid = [
        {"speaker": "elena_voss", "line": "Short open."},
        {"speaker": "eli_marsh", "line": long_line},
    ]
    assert any("monologue" in f for f in panel._craft_check(mid))
    # The same length as turn 0 (the cold-open hook) is allowed (under the hook ceiling).
    hook = [
        {"speaker": "elena_voss", "line": long_line},
        {"speaker": "eli_marsh", "line": "Reply."},
    ]
    assert panel._craft_check(hook) == []


def test_qa_review_fails_open_on_judge_error(monkeypatch):
    # If the judge/Bedrock blows up, QA must NOT block a publish (deterministic
    # safety gates are the hard floor) — returns (True, []).
    import bedrock_client

    def _boom(*a, **k):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(bedrock_client, "invoke", _boom)
    ok, fails = panel._qa_review([{"speaker": "elena_voss", "line": "hi"}], "1. anything")
    assert ok is True and fails == []
