"""#4676 — the AI coaches are described without gendered pronouns.

`/api/coach/<id>` serves `tendencies`, `voice.*`, `principles` and `relationship_to_matthew`
straight from `config/board_of_directors.json` -> members[<persona>]
(`lambdas/web/site_api_coach_profile.py::_character`). A coach is an AI persona, so a
self-description that says she/he/her/his/him about the coach is a reader-visible claim the
product does not make.

Two rules, both repo-tree only:

* board members: ZERO gendered pronouns, except the few that refer to Matthew (the subject).
  She/her/hers/herself are never allowed (Matthew is male, no coach is); he/his/him/himself
  are allowed only in a sentence (or the one before it) that names Matthew, or in an entry of `MATTHEW_REFERENTS`.
* config/coaches/*.json: a DOWN-ONLY ratchet per file (the prompt configs predate this rule
  and are heavily gendered, and they are prompt text rather than the served persona slice);
  a file may not gain a pronoun. Lower the number when you scrub one.
"""

import glob
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRONOUN = re.compile(r"\b(she|her|hers|herself|he|his|him|himself)\b", re.I)
FEMALE = {"she", "her", "hers", "herself"}

# (member, dotted path) -> the pronoun there refers to Matthew, not to the coach.
MATTHEW_REFERENTS = {
    ("cora_vance", "voice.style"),  # "...tied to his state" (the reader being coached)
    ("cora_vance", "principles.0"),  # "Never hand him the standard list"
}

# Down-only: pronoun count per prompt config. Established 2026-10-12 (#4676).
COACH_FILE_BASELINE = {
    "_shared_standard.json": 7,
    "career_coach.json": 18,
    "eli_marsh.json": 14,
    "explorer_coach.json": 13,
    "explorer_coach_stance.json": 1,
    "glucose_coach.json": 2,
    "labs_coach.json": 4,
    "mind_coach.json": 20,
    "mind_coach_stance.json": 2,
    "nutrition_coach.json": 14,
    "pattern_coach.json": 18,
    "physical_coach.json": 12,
    "sleep_coach.json": 24,
    "training_coach.json": 6,
    "tuning_log.json": 14,
}


def _strings(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(v, path + (str(k),))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _strings(v, path + (str(i),))
    elif isinstance(o, str):
        yield ".".join(path), o


def coach_pronoun_offenders(members, allow=MATTHEW_REFERENTS):
    """Every gendered pronoun in a board member that is not about Matthew."""
    out = []
    for name, m in members.items():
        for path, text in _strings(m):
            if (name, path) in allow:
                continue
            sents = re.split(r"(?<=[.!?])\s+", text)
            for i, sent in enumerate(sents):
                near = " ".join(sents[max(0, i - 1) : i + 1]).lower()  # this sentence + the one before it
                for hit in PRONOUN.finditer(sent):
                    w = hit.group(0).lower()
                    if w not in FEMALE and "matthew" in near:
                        continue
                    out.append(f"{name}.{path}: '{hit.group(0)}' in {sent[:90]!r}")
    return out


def _board():
    with open(os.path.join(ROOT, "config", "board_of_directors.json")) as f:
        return json.load(f)["members"]


def test_board_members_carry_no_gendered_pronouns():
    bad = coach_pronoun_offenders(_board())
    assert not bad, "gendered pronoun in a coach self-description (#4676):\n  " + "\n  ".join(bad)


def test_detector_catches_a_planted_pronoun():
    """Negative control: the detector must red on a coach self-reference, pass on Matthew's."""
    planted = {"x": {"personality": {"tendencies": ["Pre-empts other coaches when she sees it"]}}}
    assert coach_pronoun_offenders(planted)
    planted_he = {"x": {"relationship_to_matthew": "He owns the plan."}}
    assert coach_pronoun_offenders(planted_he)
    clean = {"x": {"relationship_to_matthew": "Matthew's deficit is aggressive; his protein matters."}}
    assert coach_pronoun_offenders(clean) == []
    assert coach_pronoun_offenders({"x": {"a": "Matthew said she"}})  # female never excused


def test_coach_prompt_configs_never_gain_a_pronoun():
    over = []
    for path in sorted(glob.glob(os.path.join(ROOT, "config", "coaches", "*.json"))):
        name = os.path.basename(path)
        with open(path) as f:
            n = len(PRONOUN.findall(f.read()))
        if n > COACH_FILE_BASELINE.get(name, 0):
            over.append(f"{name}: {n} > baseline {COACH_FILE_BASELINE.get(name, 0)}")
    assert not over, "coach prompt config gained a gendered pronoun (#4676):\n  " + "\n  ".join(over)
