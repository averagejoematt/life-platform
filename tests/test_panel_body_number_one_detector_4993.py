"""tests/test_panel_body_number_one_detector_4993.py — the Panel renderer and the story desk read ONE body-number detector.

PR #5014 fixed the desk's regex so "2.64 pounds per week" (a pace) is not a weigh-in; the Panel kept a twin that still
held the same line at render. Both now read ``content.body_numbers.BODY_NUM_RE``. The safety class is unchanged: every
spoken weigh-in figure still holds.

#5949: the published prologue spoke two weigh-ins from an earlier year — bare, no unit, not this cycle's — and nothing
held it. ``body_numbers.spoken_weight_figures`` is the detector for the shapes the unit pattern cannot see; the tests at
the bottom are its must-fail controls (the prologue's sentence SHAPE with made-up figures) and its must-pass controls.
Every figure in this file is synthetic.

Run:  python3 -m pytest tests/test_panel_body_number_one_detector_4993.py -v
"""

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "lambdas", "emails"))

from content import body_numbers, story_craft, story_writers  # noqa: E402
from emails import (  # noqa: E402
    coach_panel_podcast_lambda as panel,  # noqa: E402
    panelcast_qa,
    panelcast_scripts,
)


@pytest.fixture(autouse=True)
def _no_vice_terms(monkeypatch):
    monkeypatch.setattr(panel, "_blocked_vice_terms", lambda: [])


def test_panel_and_desk_share_one_object():
    assert story_writers._BODY_NUM_RE is body_numbers.BODY_NUM_RE
    assert not hasattr(panel, "_BODY_NUM_RE"), "a local copy of the detector is back in the Panel lambda"
    assert panel.body_numbers.BODY_NUM_RE is body_numbers.BODY_NUM_RE


@pytest.mark.parametrize(
    "line",
    [
        "the pace this window is 2.64 pounds per week, which is steady.",
        "he is losing 1.5 lbs/week on average",
        "about 2 pounds a week",
    ],
)
def test_panel_clears_rate_shapes(line):
    assert "body-number" not in panel._safety_gate(line)


@pytest.mark.parametrize(
    "line", ["he weighed 318.9 pounds that morning", "down to 46 pounds", "a 199.8 pounds reading", "312 lbs", "145 kg"]
)
def test_panel_still_holds_weigh_ins(line):
    assert "body-number" in panel._safety_gate(line)


# ── #5949: bare, worded and earlier-year figures ─────────────────────────────

# The prologue's sentence, shape for shape, with made-up figures (111 and 222 are nobody's weight).
PROLOGUE_SHAPE = "Matthew went from 111 to 222 in about eight months - then regained a significant amount after life got disrupted."
PROLOGUE_RECUT = "Matthew lost a lot of weight in about eight months - then regained much of it after life got disrupted."

MUST_HOLD = [
    PROLOGUE_SHAPE,
    "He went from 111 to 222 in eight months. The scale has not been kind since.",  # the context is the next sentence
    "The scale read 222 that morning.",  # bare, this cycle's or not
    "He weighed two hundred and twenty-two at the start.",  # in words
    "He went from two twenty-two to one-eleven before the weight came back.",  # the way it is said aloud
    "He is down nine pounds.",  # an amount, in words — the rubric's own example
    "The plan is explicit that the first ten to twelve pounds are primarily water and glycogen.",  # a range of amounts
    "The scan shows fat-free mass down nearly two pounds since Day 1.",  # a body-composition amount
    "He is down 1.9 pounds since Day 1.",  # one digit: the unit pattern needs two
]
MUST_PASS = [
    PROLOGUE_RECUT,
    "The pace this window is 2.64 pounds per week, which is steady.",  # the pace is the one figure allowed (#4993)
    "The rate flag is still active - about two and a half pounds a week, just above the threshold.",
    "Seven sessions in seven days, 813 minutes total, and the scale moved.",  # a three-digit figure with its own unit
    "The weight will move. He ate about 1,170 calories and 135 grams of protein.",
    "Recovery hit 100 percent the day the scale moved.",
    "The scale is down on Day 100.",  # a label, not a figure
    "A 174-minute hike while the scale kept falling.",
    "Protein that day: 92 grams, against a plan floor of 170.",  # no weight in the sentence
    "Weight down at high confidence over fourteen days, blood glucose down at medium.",
]


def _episode(line):
    return [{"speaker": "elena", "line": line}, {"speaker": "elena", "line": story_craft.SIGN_OFF}]


def test_every_gate_holds_a_spoken_weight_the_unit_pattern_cannot_see(monkeypatch):
    """ONE detector, three doors: the Panel renderer's safety gate, the desk's staging gate, the legacy QA gate."""
    missed = []
    for line in MUST_HOLD:
        assert not body_numbers.BODY_NUM_RE.search(line), f"not a control for #5949 — the unit pattern already holds {line!r}"
        doors = {
            "detector": bool(body_numbers.spoken_weight_figures(line)),
            "panel _safety_gate": "body-number" in panel._safety_gate(line),
            "desk spoken_word_findings": any("body-number" in f for f in story_writers.spoken_word_findings(_episode(line))),
            "panelcast_qa _craft_check": any("spoken body weight" in f for f in panelcast_qa._craft_check(_episode(line))),
            "panelcast_qa _spoken_weight_check": bool(panelcast_qa._spoken_weight_check(_episode(line))),
        }
        missed += [f"{door}: {line!r}" for door, held in doors.items() if not held]
    assert not missed, "a spoken body-weight figure cleared a gate:\n" + "\n".join(missed)
    assert len(MUST_HOLD) >= 9  # the population the loop above ran over


def test_the_pace_and_other_three_digit_figures_still_clear():
    held = []
    for line in MUST_PASS:
        doors = {
            "detector": bool(body_numbers.spoken_weight_figures(line)),
            "panel _safety_gate": "body-number" in panel._safety_gate(line),
            "desk spoken_word_findings": any("body-number" in f for f in story_writers.spoken_word_findings(_episode(line))),
            "panelcast_qa _spoken_weight_check": bool(panelcast_qa._spoken_weight_check(_episode(line))),
        }
        held += [f"{door}: {line!r}" for door, hit in doors.items() if hit]
    assert not held, "a line with no body-weight figure was held:\n" + "\n".join(held)
    assert len(MUST_PASS) >= 10


def test_episode_zero_drops_a_line_that_speaks_a_weight():
    plain = "He has done this before, and it slipped."
    worded = "He weighed two hundred and twenty-two at the start."  # no digits: ER-03 and the Day-Zero guard both pass it
    assert panel.er03_gate.er03_check(worded, allowed_numbers=set(), n=None)[0] and not panel._HALLUCINATION_RE.search(worded)
    kept = panel._gate_intro([{"speaker": "elena", "line": worded}, {"speaker": "elena", "line": plain}], set())
    assert [t["line"] for t in kept] == [plain]


def test_writers_and_judges_quote_one_rule():
    """The judge's rubric and the story desk's brief used to state two different rules ("no figure at all" against "no
    figure with units"). Every one of them now quotes body_numbers.SPOKEN_WEIGHT_RULE."""
    rule = body_numbers.SPOKEN_WEIGHT_RULE
    carriers = {
        "panelcast_qa._WEEKLY_RUBRIC": panelcast_qa._WEEKLY_RUBRIC,
        "panelcast_qa._INTRO_RUBRIC": panelcast_qa._INTRO_RUBRIC,
        "story_writers.EPISODE_VOICE": story_writers.EPISODE_VOICE,
    }
    assert not [name for name, text in carriers.items() if rule not in text]
    assert "{SPOKEN_WEIGHT_RULE}" not in story_writers.EPISODE_VOICE
    assert "figures with units" not in story_writers.EPISODE_VOICE  # the old, narrower wording
    assert not body_numbers.has_body_number(rule.split("'he lost", 1)[1])  # the rule's own example passes the gate

    seen = {}

    def _invoke(body, model_name=None):
        system = body["system"]
        seen[model_name] = system if isinstance(system, str) else "".join(b.get("text", "") for b in system)
        return {"content": [{"type": "text", "text": "[]"}]}

    class _Zeitgeist:
        @staticmethod
        def zeitgeist_prompt_block(_headlines):
            return ""

    deps = {
        "invoke": _invoke,
        "logger": panel.logger,
        "intro_guest": lambda: {"name": "Eli Marsh", "role": "PI", "philosophy": "", "expertise": []},
        "episode_angle": lambda week: "",
        "extract_json": lambda text: None,
        "zeitgeist": _Zeitgeist,
        "intro_model": "intro",
        "writer_model": "weekly",
    }
    panelcast_scripts.build_intro_script({}, [], deps)
    panelcast_scripts.build_weekly_script({"guest": {"id": "g", "name": "G"}, "coach_reads": [], "phase_block": "phase"}, {}, deps)
    assert sorted(seen) == ["intro", "weekly"]
    assert not [model for model, system in seen.items() if rule not in system]


def test_a_recut_refuses_a_weight_keeps_the_shape_and_lands_on_the_old_key():
    """scripts/panel_recut.py — the one-episode re-cut. Its refusals are pure functions; nothing here reaches AWS."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import panel_recut

    live = [{"speaker": "Elena", "line": PROLOGUE_SHAPE}, {"speaker": "Eli Marsh", "line": "Right."}]
    fixed = [{"speaker": "Elena", "line": PROLOGUE_RECUT}, {"speaker": "Eli Marsh", "line": "Right."}]
    assert panel_recut.gate_findings(live, panel._safety_gate) == ["turn 0 (Elena): body-number"]
    assert panel_recut.gate_findings(fixed, panel._safety_gate) == []
    assert panel_recut.shape_findings(live, fixed) == [] and panel_recut.changed_turns(live, fixed) == [0]
    assert panel_recut.shape_findings(live, fixed[:1]) and panel_recut.shape_findings(
        live, [fixed[0], {"speaker": "Elena", "line": "Right."}]
    )

    row = {"week": 0, "title": "EP0", "url": "/panelcast/wk0.wav", "bytes": 1, "duration_sec": 1, "excerpt": "kept"}
    assert panel_recut.recut_row(row, {"url": "/panelcast/wk0.wav", "bytes": 9, "duration_sec": 8}) == {
        **row,
        "bytes": 9,
        "duration_sec": 8,
    }

    class _Encoder:
        @staticmethod
        def compress_wav(wav_bytes):
            return (b"mp3", "mp3", "audio/mpeg")

    assert panel_recut._same_key_encoder(_Encoder, "wav")(b"RIFF") == (b"RIFF", "wav", "audio/wav")
    assert panel_recut._same_key_encoder(_Encoder, "mp3")(b"RIFF")[1] == "mp3"

    class _WavOnly:
        @staticmethod
        def compress_wav(wav_bytes):
            return (wav_bytes, "wav", "audio/wav")

    with pytest.raises(SystemExit, match="nothing was written"):
        panel_recut._same_key_encoder(_WavOnly, "mp3")(b"RIFF")
