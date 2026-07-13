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


def test_sensitivity_routing_holds_only_on_current_crisis(monkeypatch):
    # Personal Board asymmetry, post-refit (#166–182): the regex is a broad TRIGGER
    # that also fires on BACKSTORY references to past grief; an AI adjudication
    # (_is_current_crisis) then HOLDS only on a genuine CURRENT-WEEK crisis (fail-
    # closed). We mock the adjudication so the gate is deterministic and offline —
    # the old assertion both expected the pre-refit auto-hold AND called live Bedrock.

    # 1) Sensitive text adjudicated as a CURRENT crisis → HOLD (route to a human).
    monkeypatch.setattr(panel, "_is_current_crisis", lambda text: True)
    assert panel._sensitivity_hold_reasons({"chronicle": "A relapse week; felt hopeless for a stretch."})

    # 2) Same broad trigger, but adjudicated as BACKSTORY (not current) → NO hold.
    #    This is the regression the refit fixed: a strong week that merely references
    #    past grief must not be auto-held.
    monkeypatch.setattr(panel, "_is_current_crisis", lambda text: False)
    assert panel._sensitivity_hold_reasons({"chronicle": "This week was heavy — grief has a way of resurfacing."}) == []

    # 3) A clean week never trips the trigger regex → no hold (adjudication never runs).
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


def test_craft_check_allows_two_but_flags_three_in_a_row():
    # #1171 re-calibration (2026-07-12): the Haiku judge's rubric failed every script
    # containing 3-in-a-row, so the deterministic bound now agrees — 2 same-speaker
    # turns read fine; 3+ is the floor-hog that fails BOTH graders.
    two = [
        {"speaker": "elena_voss", "line": "One."},
        {"speaker": "eli_marsh", "line": "Two."},
        {"speaker": "eli_marsh", "line": "Three."},
        {"speaker": "elena_voss", "line": "Four."},
    ]
    assert panel._craft_check(two) == []  # exactly 2 eli in a row — allowed
    three = [
        {"speaker": "elena_voss", "line": "One."},
        {"speaker": "eli_marsh", "line": "Two."},
        {"speaker": "eli_marsh", "line": "Three."},
        {"speaker": "eli_marsh", "line": "Four."},
    ]
    fails = panel._craft_check(three)
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


def test_qa_review_fails_closed_on_judge_error(monkeypatch):
    # #1122: if the judge/Bedrock blows up, QA must fail CLOSED — the episode holds
    # instead of publishing unreviewed (judge failure means silence, not a broken
    # episode). Inverts the pre-#1122 fail-open behavior.
    import bedrock_client

    def _boom(*a, **k):
        raise RuntimeError("bedrock down")

    monkeypatch.setattr(bedrock_client, "invoke", _boom)
    ok, fails = panel._qa_review([{"speaker": "elena_voss", "line": "hi"}], "1. anything")
    assert ok is False
    assert fails and "fail-closed" in fails[0] and "bedrock down" in fails[0]


# ── #1122: deterministic conversational-continuity gate ──────────────────────


def test_continuity_flags_missing_reply_to_challenge():
    # The observed wk0 defect: Elena challenges ("convince me...") and the guest's
    # reply was dropped, so the NEXT turn is Elena again ("here's where I push back").
    turns = [
        {"speaker": "elena_voss", "line": "Here's the hook that got me."},
        {"speaker": "eli_marsh", "line": "A good place to start."},
        {"speaker": "elena_voss", "line": "Convince me this isn't just a beautiful dashboard."},
        {"speaker": "elena_voss", "line": "And here's where I push back the hardest."},
        {"speaker": "eli_marsh", "line": "That's fair."},
    ]
    fails = panel._continuity_check(turns)
    assert fails and "dangling thread" in fails[0] and "turn 2" in fails[0]
    # And it surfaces through the combined deterministic craft gate (post-drop entry point).
    assert any("dangling thread" in f for f in panel._craft_check(turns))


def test_continuity_flags_post_drop_question_hole():
    # A gate dropped the answer to a direct question, leaving asker→asker adjacency.
    turns = [
        {"speaker": "elena_voss", "line": "Welcome back to the show."},
        {"speaker": "eli_marsh", "line": "Glad to be here."},
        {"speaker": "elena_voss", "line": "So what does the data actually show this week?"},
        # eli's answer was dropped by a safety/number gate →
        {"speaker": "elena_voss", "line": "Let's talk about the week ahead."},
        {"speaker": "eli_marsh", "line": "Happy to."},
    ]
    fails = panel._continuity_check(turns)
    assert fails and "asks a question" in fails[0] and "turn 2" in fails[0]


def test_continuity_passes_healthy_script_and_sanctioned_solo_turns():
    # Healthy alternating dialogue — including a question that IS answered — passes.
    healthy = [
        {"speaker": "elena_voss", "line": "Can a system catch what willpower misses?"},  # turn-0 hook: exempt by design
        {"speaker": "elena_voss", "line": "I'm Elena Voss, and that's the question I couldn't put down."},
        {"speaker": "eli_marsh", "line": "It's the right question to open on."},
        {"speaker": "elena_voss", "line": "So convince me this isn't theater."},
        {"speaker": "eli_marsh", "line": "Here's my honest case for why it isn't."},
        {"speaker": "elena_voss", "line": "Does the tech genuinely make a life better, or is it theater?"},  # closing question: exempt
    ]
    assert panel._continuity_check(healthy) == []
    assert panel._craft_check(healthy) == []


def test_run_intro_holds_on_qa_fails_never_publishes(monkeypatch):
    # #1122 hard gate: a best candidate that still fails QA after all re-rolls must
    # HOLD (regenerate-or-hold, ADR-087) — never publish. Judge exception drives the
    # fail here, covering the fail-closed path end-to-end.
    import bedrock_client

    monkeypatch.setattr(panel, "_load_bible", lambda: {"characters": {"matthew": "an ordinary, technical, curious person"}})
    clean_script = [
        {"speaker": ("elena" if i % 2 == 0 else "eli"), "line": "I'm Elena Voss and this is a clean, number-free line of dialogue."}
        for i in range(10)
    ]
    monkeypatch.setattr(panel, "_build_intro_script", lambda bible, **k: [dict(t) for t in clean_script])
    monkeypatch.setattr(bedrock_client, "invoke", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("judge down")))

    held = {}

    def _fake_hold(week, reasons, draft, hold_class="safety"):
        held.update({"week": week, "reasons": reasons, "hold_class": hold_class})
        return {"statusCode": 200, "body": "{}", "held": True}

    monkeypatch.setattr(panel, "_hold_and_alert", _fake_hold)
    monkeypatch.setattr(
        panel, "_publish_episode_audio", lambda *a, **k: (_ for _ in ()).throw(AssertionError("published despite QA fails"))
    )
    # #1172: exhaustion now escalates via ONE email — keep it offline here and assert it fired once.
    emails = []
    monkeypatch.setattr(panel._repair, "send_exhaustion_email", lambda *a, **k: emails.append(a) or {"sent": 1})

    out = panel._run_intro(dry_run=False)
    assert out.get("held") is True
    assert held["week"] == 0 and held["hold_class"] == "quality"
    assert any("qa-judge-error" in r or "intro-qa" in r for r in held["reasons"])
    assert len(emails) == 1


# ── #374: podcast-standard feed + per-run reason codes ───────────────────────

_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
_ATOM = "http://www.w3.org/2005/Atom"


def _render_feed(monkeypatch, episodes):
    """Capture the feed.xml body _write_indexes writes, without touching S3/CDN."""
    captured = {}

    def _put(**kw):
        if kw.get("Key", "").endswith("feed.xml"):
            captured["feed"] = kw["Body"]
        return {}

    monkeypatch.setattr(panel.s3, "put_object", lambda **kw: _put(**kw))
    monkeypatch.setattr(panel, "_invalidate_cdn", lambda: None)
    panel._write_indexes(episodes)
    return captured["feed"]


def test_feed_is_well_formed_and_podcast_standard(monkeypatch):
    import xml.etree.ElementTree as ET

    eps = [
        {
            "week": 3,
            "title": "EP3 · The Wall",
            "date": "2026-06-30",
            "url": "/panelcast/wk3.wav",
            "bytes": 12897210,
            "duration_sec": 402,
            "excerpt": "The week the data hit a wall.",
            "image_url": "",
        },
        {
            "week": 0,
            "title": "EP0 · Welcome",
            "date": "2026-06-18",
            "url": "/panelcast/wk0.mp3",
            "bytes": 1003200,
            "duration_sec": 250,
            "excerpt": "Meet the Panel.",
            "image_url": "",
        },
    ]
    feed = _render_feed(monkeypatch, eps)
    root = ET.fromstring(feed)  # noqa: S314 — our own generated feed (trusted); raises on malformed XML
    ch = root.find("channel")
    # Apple-required channel tags
    assert ch.find(f"{{{_ITUNES}}}image").get("href")
    assert ch.find(f"{{{_ITUNES}}}category").get("text")
    owner = ch.find(f"{{{_ITUNES}}}owner")
    assert owner.find(f"{{{_ITUNES}}}email").text and "@" in owner.find(f"{{{_ITUNES}}}email").text
    assert ch.find(f"{{{_ITUNES}}}explicit").text == "false"
    assert ch.find(f"{{{_ITUNES}}}type").text == "episodic"
    self_link = ch.find(f"{{{_ATOM}}}link")
    assert self_link.get("rel") == "self" and self_link.get("href").endswith("/panelcast/feed.xml")
    # every item has an enclosure with a correct-per-file MIME + duration + episode number
    items = ch.findall("item")
    assert len(items) == 2
    by_wav = next(i for i in items if i.find("enclosure").get("url").endswith(".wav"))
    by_mp3 = next(i for i in items if i.find("enclosure").get("url").endswith(".mp3"))
    assert by_wav.find("enclosure").get("type") == "audio/wav"
    assert by_mp3.find("enclosure").get("type") == "audio/mpeg"
    for it in items:
        assert it.find("enclosure").get("length")
        assert it.find(f"{{{_ITUNES}}}duration").text.count(":") == 2  # HH:MM:SS
        assert it.find(f"{{{_ITUNES}}}episode").text
        assert it.find("guid").text.startswith("measured-life-panel-wk")


def test_hms_formats_seconds():
    assert panel._hms(402) == "0:06:42"
    assert panel._hms(3725) == "1:02:05"
    assert panel._hms(None) == "0:00:00"


def test_enclosure_mime_by_extension():
    assert panel._enclosure_type("/panelcast/wk3.wav") == "audio/wav"
    assert panel._enclosure_type("/panelcast/wk0.mp3") == "audio/mpeg"
    assert panel._enclosure_type("/panelcast/wk4.m4a") == "audio/mp4"


def test_reason_codes_cover_every_terminal_outcome():
    # the vocabulary the alarm reads — published + the distinct silence causes.
    for r in ("published", "held-quality", "held-safety", "no-input", "error"):
        assert r in panel._OUTCOME_REASONS


def test_emit_outcome_is_fail_open_and_normalizes(monkeypatch):
    calls = []

    class _CW:
        def put_metric_data(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(panel.boto3, "client", lambda *a, **k: _CW())
    panel._emit_outcome("held-quality")
    md = calls[0]["MetricData"][0]
    assert md["MetricName"] == "PanelcastRun"
    assert md["Dimensions"][0] == {"Name": "Reason", "Value": "held-quality"}
    # an unknown reason is coerced to "error", never raises
    panel._emit_outcome("bogus")
    assert calls[1]["MetricData"][0]["Dimensions"][0]["Value"] == "error"
