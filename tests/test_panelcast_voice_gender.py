"""Guard: every podcast persona's TTS voice must match the persona's gender.

Regression test for the 2026-06-21 bug where the panelcast's hardcoded voice table had
Marcus Webb (male) on a female voice and Sarah Chen (female) on a male one. The
registry (config/personas.json) is the single source of truth; the panelcast now derives
the Gemini voice from each persona's tts_voice suffix, so this test locks the source clean.
"""

import json
import os

# Gemini / Chirp3-HD prebuilt voice genders (the suffix of en-US-Chirp3-HD-<Name>).
MALE_VOICES = {
    "Charon",
    "Fenrir",
    "Puck",
    "Orus",
    "Iapetus",
    "Enceladus",
    "Algenib",
    "Algieba",
    "Alnilam",
    "Rasalgethi",
    "Sadachbia",
    "Sadaltager",
    "Schedar",
    "Umbriel",
    "Zubenelgenubi",
    "Achird",
}
FEMALE_VOICES = {
    "Aoede",
    "Kore",
    "Leda",
    "Zephyr",
    "Callirrhoe",
    "Autonoe",
    "Despina",
    "Erinome",
    "Gacrux",
    "Pulcherrima",
    "Vindemiatrix",
    "Sulafat",
    "Achernar",
    "Laomedeia",
}

# Expected gender per persona, by their (fictional) display name.
EXPECTED_GENDER = {
    "elena_voss": "F",  # Elena Voss
    "eli_marsh": "M",  # Eli Marsh
    "sleep_coach": "F",  # Lisa Park
    "training_coach": "F",  # Sarah Chen
    "nutrition_coach": "M",  # Marcus Webb
    "mind_coach": "M",  # Nathan Reeves
    "physical_coach": "M",  # Victor Reyes
    "glucose_coach": "F",  # Amara Patel
    "labs_coach": "M",  # James Okafor
    "explorer_coach": "M",  # Henning Brandt
}


def _personas():
    path = os.path.join(os.path.dirname(__file__), "..", "config", "personas.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh).get("personas", {})


def test_persona_voice_matches_gender():
    personas = _personas()
    for pid, gender in EXPECTED_GENDER.items():
        assert pid in personas, f"missing persona {pid}"
        voice = (personas[pid].get("tts_voice") or "").rsplit("-", 1)[-1]
        pool = MALE_VOICES if gender == "M" else FEMALE_VOICES
        name = personas[pid].get("name")
        assert voice, f"{pid} ({name}) has no tts_voice"
        assert voice in pool, f"{pid} ({name}) expected a {gender} voice, got '{voice}' (gender-mismatched)"
