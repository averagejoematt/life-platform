"""#4676 — the AI coaches are described without gendered pronouns.

`/api/coach/<id>` serves `tendencies`, `voice.*`, `principles` and `relationship_to_matthew`
straight from `config/board_of_directors.json` -> members[<persona>]
(`lambdas/web/site_api_coach_profile.py::_character`). A coach is an AI persona, so a
self-description that says she/he/her/his/him about the coach is a reader-visible claim the
product does not make.

Two rules, both repo-tree only:

* board members: ZERO gendered pronouns, except the few that refer to Matthew (the subject).
  She/her/hers/herself are never allowed (Matthew is male, no coach is); he/his/him/himself
  are allowed only after "Matthew" in the same sentence, or in an entry of `MATTHEW_REFERENTS` /
  `MATTHEW_SENTENCES` (an explicit allowlist, so a coach "He" next to a Matthew sentence is still flagged).
* config/coaches/<id>.json: the SERVED slice (`site_api_coach_profile._voice_subset`: decision_style,
  structural_voice_rules, few_shot_examples[0]) gets the same ZERO rule, as `voice.*` on `/api/coach/<id>`.
  The rest of each prompt config (unserved prompt text) keeps a DOWN-ONLY ratchet per file;
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

# (coach file, dotted path in the served slice) -> the pronoun refers to Matthew.
SERVED_MATTHEW_REFERENTS = {
    ("mind_coach.json", "structural_voice_rules.signature_moves.1"),  # "in his journal" (Matthew's)
}

# (member, dotted path, sentence prefix): a male pronoun in that exact sentence refers to Matthew.
# Each was read and confirmed 2026-10-12; a coach "He" in any other sentence is flagged.
MATTHEW_SENTENCES = {
    ("sarah_chen", "relationship_to_matthew", "His tendency to push hard"),
    ("sarah_chen", "features.weekly_digest.prompt_focus", "What does the Banister model"),
    ("marcus_webb", "relationship_to_matthew", "His deficit is aggressive"),
    ("lisa_park", "relationship_to_matthew", "His weight loss depends"),
    ("maya_rodriguez", "relationship_to_matthew", "He is also the sole developer"),
    ("rhonda_patrick", "relationship_to_matthew", "Patrick bridges his genome data"),
    ("elena_voss", "relationship_to_matthew", "Elena is invested in his story"),
    ("amara_patel", "relationship_to_matthew", "Particularly interested in his meal timing"),
    ("cora_vance", "relationship_to_matthew", "Cora periodizes his reading"),
}

# Down-only: pronoun count per prompt config. Established 2026-10-12 (#4676).
COACH_FILE_PRONOUN_COUNTS = {
    "_shared_standard.json": 7,
    "career_coach.json": 14,
    "eli_marsh.json": 11,
    "explorer_coach.json": 11,
    "explorer_coach_stance.json": 1,
    "mind_coach.json": 17,
    "mind_coach_stance.json": 2,
    "nutrition_coach.json": 12,
    "pattern_coach.json": 12,
    "physical_coach.json": 9,
    "sleep_coach.json": 21,
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
            for sent in sents:
                for hit in PRONOUN.finditer(sent):
                    w = hit.group(0).lower()
                    # male pronoun excused only AFTER "Matthew" in the same sentence
                    if w not in FEMALE and "matthew" in sent[: hit.start()].lower():
                        continue
                    if w not in FEMALE and any((name, path) == (n, p) and sent.startswith(s) for n, p, s in MATTHEW_SENTENCES):
                        continue
                    out.append(f"{name}.{path}: '{hit.group(0)}' in {sent[:90]!r}")
    return out


def served_voice_offenders(files):
    """files: {name: parsed config}. Pronouns in the slice `/api/coach/<id>` serves as `voice`."""
    out = []
    for name, cfg in files.items():
        examples = cfg.get("few_shot_examples") or []
        served = {
            "decision_style": cfg.get("decision_style"),
            "structural_voice_rules": cfg.get("structural_voice_rules"),
            "few_shot_examples": {"0": examples[0]} if examples else None,
        }
        out += coach_pronoun_offenders({name: served}, allow={(name, p) for n, p in SERVED_MATTHEW_REFERENTS if n == name})
    return out


def _coach_configs():
    out = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "config", "coaches", "*.json"))):
        with open(path) as f:
            out[os.path.basename(path)] = json.load(f)
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
        if n > COACH_FILE_PRONOUN_COUNTS.get(name, 0):
            over.append(f"{name}: {n} > baseline {COACH_FILE_PRONOUN_COUNTS.get(name, 0)}")
    assert not over, "coach prompt config gained a gendered pronoun (#4676):\n  " + "\n  ".join(over)


def test_served_coach_voice_carries_no_gendered_pronouns():
    """What /api/coach/<id> serves as `voice` (from config/coaches/<id>.json) is pronoun-free."""
    bad = served_voice_offenders(_coach_configs())
    assert not bad, "gendered pronoun in the served coach voice (#4676):\n  " + "\n  ".join(bad)


def test_served_detector_catches_a_planted_pronoun():
    planted = {"x.json": {"decision_style": {"revision_style": "explain what the data taught her."}}}
    assert served_voice_offenders(planted)
    later_example = {"x.json": {"few_shot_examples": [{"output": "clean"}, {"output": "she said"}]}}
    assert served_voice_offenders(later_example) == []  # only the first example is served
    assert served_voice_offenders({"x.json": {"few_shot_examples": [{"output": "she said"}]}})
    # a coach "He" right after a sentence about Matthew is NOT excused
    assert coach_pronoun_offenders({"x": {"r": "Matthew sleeps badly. He flags it before anyone else."}})
    assert coach_pronoun_offenders({"x": {"r": "Matthew's plan is his own."}}) == []


# premerge-gate: #4676: glob sweep of config/coaches/*.json + board members — no gendered pronoun in a coach self-description
