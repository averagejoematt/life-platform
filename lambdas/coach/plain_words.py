"""plain_words.py — can a friend read this line? The deterministic check on a coach's watch list (#4649).

A coach's stance carries a short list, ``focused_on_now``, that the site prints word for
word under "watching now". The list was written in the trade's terms — one served item
read "Protein intake stabilization at threshold as a mechanistic lever for slow-wave
architecture" — and a reader with no training in the field closed the page on it. The
page may not reword a coach, so the rule is applied where the words are made and where
they are served:

  * ``coach_history_summarizer`` (the writer) asks for plain words, checks each item,
    asks once more when one fails, and stores only the items that pass;
  * ``web.site_api_coach_stance`` (the route) runs the same check on the stored list, so
    an item written before this rule existed is withheld today rather than after the
    next weekly run.

A withheld item is absent. Nothing stands in for it.

THE RULE — one item passes when ALL of these hold:

  1. it is at most ``MAX_CHARS`` (80) characters;
  2. it has no word of ``TOO_LONG_WORD`` (13) or more letters;
  3. it has at most ``MAX_LONG_WORDS`` (1) word of ``LONG_WORD`` (11) or more letters;
  4. it uses none of the reader-vocabulary registry's renamed or cut terms.

No model is called and no list of specialist terms is kept: long words stand in for
jargon ("stabilization", "interpretation", and "mechanistic" beside "architecture"), which is crude
and is the point — the rule can be read in one breath and checked by hand. A hyphenated
compound counts as its parts ("slow-wave" is "slow" and "wave").

``REGISTRY_TERMS`` is a copy of the ``rename`` and ``cut`` rulings in
``site/data/glossary.json`` (the one reader vocabulary, #4182), because a Lambda cannot
read the site tree. ``tests/test_coach_plain_words_4649.py`` holds the copy equal to the
registry, so a ruling added there fails the build until it is copied here.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

MAX_CHARS = 80
LONG_WORD = 11
MAX_LONG_WORDS = 1
TOO_LONG_WORD = 13
# A pending call is a whole sentence, not a watch phrase: it gets a longer cap, the rest of the rule is the same (#4714).
CALL_MAX_CHARS = 160

# Trade terms a short word can carry past the length rules (#4714): the live sleep page printed "Protein-slow-wave
# hypothesis could activate once protein EWMA reaches 145g+ threshold." Whole words, any case; a hyphenated
# compound is matched on its parts ("slow-wave" is "slow wave"). Deliberately short: this is the specimen's class.
JARGON_TERMS: tuple[str, ...] = ("EWMA", "EMA", "slow wave", "hypothesis", "z-score", "sigma", "baseline-adjusted", "autocorrelation")

# The registry's renamed and cut terms, in registry order. Held equal to the registry by test.
REGISTRY_TERMS: tuple[str, ...] = ("reset", "chronicle", "model", "as of", "Third Wall", "pillar", "pace flag", "gate", "character level")

_WORD_RE = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?")


def _term_re(term: str) -> re.Pattern[str]:
    # Same matching as tests/test_site_vocabulary_registry.py: word-bounded, any case, and a
    # space in the term also matches an underscore.
    return re.compile(r"(?<![A-Za-z0-9])" + re.escape(term).replace(r"\ ", r"[\s_]") + r"(?![A-Za-z0-9])", re.I)


_REGISTRY_RES = tuple((term, _term_re(term)) for term in REGISTRY_TERMS)
_JARGON_RES = tuple(
    (term, re.compile(r"(?<![A-Za-z0-9])" + re.escape(term).replace(r"\ ", r"[\s_-]") + r"(?![A-Za-z0-9])", re.I)) for term in JARGON_TERMS
)


def reasons(text: Any, max_chars: int = MAX_CHARS) -> list[str]:
    """Why this item is not plain, one short reason per broken rule. Empty when it passes."""
    if not isinstance(text, str) or not text.strip():
        return ["empty"]
    item = text.strip()
    out = []
    if len(item) > max_chars:
        out.append(f"{len(item)} characters (the cap is {max_chars})")
    words = [w.replace("’", "'").split("'")[0] for w in _WORD_RE.findall(item)]
    too_long = sorted({w.lower() for w in words if len(w) >= TOO_LONG_WORD})
    if too_long:
        out.append("a word of %d or more letters: %s" % (TOO_LONG_WORD, ", ".join(too_long)))
    long_words = [w.lower() for w in words if len(w) >= LONG_WORD]
    if len(long_words) > MAX_LONG_WORDS:
        out.append("more than %d word of %d or more letters: %s" % (MAX_LONG_WORDS, LONG_WORD, ", ".join(long_words)))
    used = [term for term, rx in _REGISTRY_RES if rx.search(item)]
    if used:
        out.append("a word the site does not use with readers: %s" % ", ".join(used))
    jargon = specialist_terms(item)
    if jargon:
        out.append("a specialist term: %s" % ", ".join(jargon))
    return out


def specialist_terms(text: Any) -> list[str]:
    """The JARGON_TERMS this text uses, in list order — the jargon half of the rule alone, with no length rule.
    A sealed pre-registered bet is judged on this only, and only to label it: it is never dropped (#4714)."""
    if not isinstance(text, str):
        return []
    return [term for term, rx in _JARGON_RES if rx.search(text)]


def is_plain(text: Any, max_chars: int = MAX_CHARS) -> bool:
    """True when a friend with no training in the field could read this item."""
    return not reasons(text, max_chars)


def plain_items(items: Any, max_chars: int = MAX_CHARS) -> list[str]:
    """The items that pass, in their order. Anything else is dropped; nothing replaces it."""
    if not isinstance(items, (list, tuple)):
        return []
    return [item for item in items if is_plain(item, max_chars)]


def failing(items: Any, max_chars: int = MAX_CHARS) -> list[str]:
    """The non-empty items that do not pass, in their order."""
    if not isinstance(items, (list, tuple)):
        return []
    return [item for item in items if isinstance(item, str) and item.strip() and not is_plain(item, max_chars)]


def correction(items: Iterable[str]) -> str:
    """The one corrective instruction the writer sends when a watch item is not plain."""
    bad = list(items)
    if not bad:
        return ""
    quoted = "; ".join('"%s"' % item for item in bad)
    return (
        "\n\nSTRICT CORRECTION: these 'focused_on_now' / 'set_aside_for_now' items are not plain enough for a general reader and "
        f"will not be shown: {quoted}. Rewrite every item as one short phrase a friend with no training in "
        f"this field could read: everyday words, at most {MAX_CHARS} characters, no specialist term."
    )
