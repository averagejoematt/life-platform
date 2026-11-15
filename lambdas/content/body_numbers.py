"""The ONE body-number detector (#4993), and the ONE statement of the spoken-weight rule (#5949).

The story desk's staging gate and the Panel renderer's fail-closed safety gate both read this module, so a line that
clears one cannot be held by the other.

THE RULE (``SPOKEN_WEIGHT_RULE`` — every writer brief and judge rubric quotes this constant, so they cannot disagree):
no body-weight or body-mass figure is spoken. That is a weigh-in from any period (this experiment's or an earlier
year's), with its unit or without, in digits or in words, and an amount of weight or mass lost, gained or regained
(fat, lean and fat-free mass included). The one figure that may be spoken is the pace per week (#4993).

Two detectors, both deterministic:

  ``BODY_NUM_RE``            a two- or three-digit figure next to a weight unit ("318.9 pounds", "145 kg"). Not the
                             tail of a decimal ("2.64"), not a weight followed by a rate unit ("2.64 pounds per week").
  ``spoken_weight_figures``  the shapes that pattern cannot see (#5949 — a published prologue spoke two weigh-ins from
                             an earlier year, bare, and nothing held it): a bare three-digit figure in a weight
                             sentence, a figure written in words, and a small amount next to a weight unit.

``spoken_weight_figures`` fails closed. A bare three-digit figure in a weight sentence clears only when a unit from
``_OTHER_UNIT`` follows it or a label from ``_LABEL_BEFORE`` precedes it; an unfamiliar unit holds the line for a person.
"""

import re
from typing import List

SPOKEN_WEIGHT_RULE = (
    "NO BODY WEIGHT IS SPOKEN: no body-weight or body-mass figure in any spoken line — not a weigh-in from this "
    "experiment or from any earlier year, not with its unit and not bare (a bare three-digit number in a sentence about "
    "his weight is a weigh-in), not in digits and not in words ('nine pounds' is as forbidden as '250 lbs'), and not an "
    "amount of weight, fat, lean or fat-free mass lost, gained or regained. The ONE figure that may be spoken is the "
    "pace per week ('about two and a half pounds a week'). Otherwise talk about direction and pace against the plan: "
    "'he lost a lot of weight in about eight months, then regained much of it'."
)

_UNIT = r"(?:lbs?|pounds?|kgs?|kilos?|kilograms?)"
_RATE_TAIL = r"(?:\s*/\s*(?:week|wk|w)\b|\s+(?:per|a|each|every)\s+week\b)"
BODY_NUM_RE = re.compile(r"(?<![\d.,])\b\d{2,3}(?:\.\d+)?\s?(?:lb|lbs|pound|pounds|kg|kilo|kilos|kilograms)\b(?!" + _RATE_TAIL + ")", re.I)

_SENTENCE = re.compile(r"[^.!?]*(?:\.(?=\d)[^.!?]*)*[.!?]*")
# A sentence is about his weight when it names the scale, a weigh-in, his weight, a weight unit, body mass, or weight
# coming back ("weights" stays out: lifting them says nothing about the scale — the story_craft convention).
_WEIGHT_CTX = re.compile(
    r"\b(?:weigh(?:s|ed|ing|-ins?)?|weight|bodyweight|scale|regain\w*|heavier|lighter|"
    r"lean mass|fat mass|body mass|body fat|fat-free)\b|\b" + _UNIT + r"\b",
    re.I,
)
# Units and labels that make a three-digit figure something other than a weight. Anything else is a weigh-in.
_OTHER_UNIT = (
    r"(?:\s?%|\s*-?\s*(?:percent|grams?|g|mg|milligrams?|calories?|kcal|cals?|minutes?|mins?|hours?|hrs?|seconds?|secs?|"
    r"days?|nights?|weeks?|months?|years?|steps?|miles?|km|kilometers?|meters?|feet|ft|reps?|sets?|sessions?|workouts?|"
    r"milliseconds?|ms|bpm|beats|points?|watts?|times|predictions?|calls?|bets?|meals?|entries|readings?|people|coaches)\b)"
)
_LABEL_BEFORE = re.compile(r"(?:\b(?:day|week|episode|ep|issue|page|chapter|number|no\.?)\s|[#$])$", re.I)
_BARE_3 = re.compile(r"(?<![\w.,/:-])\d{3}(?:\.\d+)?(?![\w/:]|[.,]\d)(?!" + _OTHER_UNIT + ")")
# "from 250 to 180": the prologue's shape. It needs weight context anywhere in the turn, not in its own sentence.
_FROM_TO = re.compile(
    r"\bfrom\s+(?:about\s+|around\s+|roughly\s+|nearly\s+)?\d{3}(?:\.\d+)?\s+(?:down\s+|up\s+)?to\s+"
    r"(?:about\s+|around\s+|roughly\s+|nearly\s+)?\d{3}(?:\.\d+)?(?![\w/:]|[.,]\d)(?!" + _OTHER_UNIT + ")",
    re.I,
)

_ONES = r"(?:one|two|three|four|five|six|seven|eight|nine)"
_TEENS = r"(?:ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen)"
_TENS = r"(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
_SUB_100 = rf"(?:{_TENS}(?:[\s-]{_ONES})?|{_TEENS}|{_ONES})"
_HUNDRED = rf"(?:(?:a|{_ONES})\s+hundred(?:\s+(?:and\s+)?{_SUB_100})?)"
# "three-oh-five", "one ninety", "two fifteen": how a three-digit weight is said aloud.
_COLLOQUIAL = rf"(?:(?:one|two|three|four)[\s-](?:oh[\s-]{_ONES}|{_TENS}(?:[\s-]{_ONES})?|{_TEENS}))"
_WORD_NUM = rf"(?:{_HUNDRED}|{_COLLOQUIAL}|{_SUB_100}|a\s+couple(?:\s+of)?|a\s+few|half\s+a)"
_AMOUNT = rf"(?:(?:\d+(?:\.\d+)?|{_WORD_NUM})(?:\s+(?:to|or)\s+(?:\d+(?:\.\d+)?|{_WORD_NUM}))?(?:\s+and\s+a\s+half)?)"
# Any amount next to a weight unit, unless a per-week rate follows: "nine pounds", "ten to twelve pounds", "1.9 lbs".
_AMOUNT_WITH_UNIT = re.compile(rf"(?<![\w.,])\b{_AMOUNT}[\s-]{_UNIT}\b(?!{_RATE_TAIL})", re.I)
# A three-digit weight in words with no unit, in a weight sentence: "three hundred and five", "one ninety".
_WORDS_3 = re.compile(rf"\b(?:{_HUNDRED}|{_COLLOQUIAL})\b(?!{_OTHER_UNIT})(?!\s*(?:a\.?m\.?|p\.?m\.?|o'clock)\b)", re.I)


def _bare(rx: "re.Pattern[str]", text: str) -> List[str]:
    return [m.group(0) for m in rx.finditer(text) if not _LABEL_BEFORE.search(text[: m.start()])]


def spoken_weight_figures(text: str) -> List[str]:
    """Every body-weight figure in a spoken line that ``BODY_NUM_RE`` does not see (#5949). Empty = none found."""
    t = text or ""
    found = [m.group(0) for m in _AMOUNT_WITH_UNIT.finditer(t)]
    for sentence in _SENTENCE.findall(t):
        if _WEIGHT_CTX.search(sentence):
            found += _bare(_BARE_3, sentence) + _bare(_WORDS_3, sentence)
    if _WEIGHT_CTX.search(t):
        found += [m.group(0) for m in _FROM_TO.finditer(t)]
    out: List[str] = []
    for f in found:
        f = f.strip()
        if f and not any(f in kept for kept in out):
            out = [kept for kept in out if kept not in f] + [f]
    return out


def has_body_number(text: str) -> bool:
    """The whole rule as one predicate: either detector fires."""
    return bool(BODY_NUM_RE.search(text or "") or spoken_weight_figures(text))
