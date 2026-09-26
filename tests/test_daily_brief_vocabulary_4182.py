"""tests/test_daily_brief_vocabulary_4182.py — the daily brief speaks the site's plain vocabulary.

#4182 (the reader-vocabulary rulings, ``site/data/glossary.json``) applied to the email the
owner reads every morning. One rendered brief — every optional section on (the engine's
score with level events, protocol recommendations, habit tiers and streaks, the Sunday
weekly habit review, the data-status banner) — is reduced to its human-facing TEXT (tags,
comments and styles stripped) and read for the builder words the rulings retired:

  * no ISO date anywhere, and never "as of" — dates are in words, with ONE
    "Data through <day>" freshness line at the top;
  * no "pillar", no "Character Level"/"CHARACTER SHEET", no "T0"/"T1" tier codes,
    no "reset".

Served coach text is the exception the rulings name ("Not in these hours: no rewriting
SERVED coach text"): the coach paragraphs are shown verbatim, even when they use a
builder word or an ISO date. The second test pins that the renderer passes them through
untouched rather than "fixing" them.

Scope: this file renders ONE fixture through ``html_builder.build_html`` and the banner
builder. It is not a tree sweep.
"""

import html as _html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from test_daily_brief_golden import KWARGS  # noqa: E402 — the golden's frozen packet, reused

_CHARACTER = {
    "character_level": 21,
    "character_tier": "Momentum",
    "character_tier_emoji": "⚡",
    "character_xp": 4200,
    "level_events": [
        {"type": "character_level_up", "old_level": 20, "new_level": 21},
        {"type": "pillar_level_up", "pillar": "mind", "old_level": 8, "new_level": 9},
    ],
    **{
        "pillar_" + p: {"level": 10, "tier": "Foundation"}
        for p in ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency")
    },
}

_WEEKLY = {
    "days": 7,
    "measured_days": 6,
    "daily": [
        {"date": "2026-06-08", "t0_done": 4, "t0_total": 4, "t0_pct": 1.0, "perfect": True, "missed": []},
        {"date": "2026-06-09", "t0_done": 2, "t0_total": 4, "t0_pct": 0.5, "perfect": False, "missed": ["Lift"]},
    ],
    "perfect_days": 1,
    "avg_t0_pct": 0.75,
    "avg_t1_pct": 0.6,
    "t0_habits": [{"name": "Lift", "days_done": 1, "days_total": 2, "pct": 0.5}],
    "synergy": {},
}

_DETAILS = {"habits_mvp": {"tier0": {"done": 5, "total": 7}, "tier1": {"done": 2, "total": 4}}}

# A served coach paragraph that uses builder words and an ISO date on purpose.
_SERVED = "Your sleep pillar held on 2026-06-09, as of the last reset."


def _render(**over):
    from content.html_builder import build_html

    kw = {
        **KWARGS,
        "character_sheet": _CHARACTER,
        "component_details": _DETAILS,
        "mvp_streak": 12,
        "full_streak": 3,
        "weekly_habit_review": _WEEKLY,
        "protocol_recs": [{"pillar": "sleep", "dropped": True, "protocols": ["Magnesium"]}],
        "data": {**KWARGS["data"], "hrv": {"hrv_7d": 44, "hrv_30d": 42}},
    }
    kw.update(over)
    return build_html(**kw)


def _banner():
    from emails.brief_data_status import build_data_status_banner_html

    stale = [{"source": "whoop", "age_days": 5, "last_date": "2026-06-05"}]
    quiet = [{"source": "macrofactor", "label": "MacroFactor", "age_days": 45, "last_date": "2026-04-26", "quiet_after_days": 14}]
    return build_data_status_banner_html(stale, quiet)


def _text(fragment: str) -> str:
    """The words a person reads: comments, styles and tags stripped, entities decoded."""
    t = re.sub(r"(?s)<!--.*?-->", " ", fragment)
    t = re.sub(r"(?s)<style.*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", _html.unescape(t))


_RETIRED = [
    ("an ISO date", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),
    ('"as of"', re.compile(r"\bas of\b", re.IGNORECASE)),
    ('"pillar"', re.compile(r"\bpillars?\b", re.IGNORECASE)),
    ('"Character Level"', re.compile(r"\bcharacter (level|sheet)\b", re.IGNORECASE)),
    ('"T0 Streak" / a tier code', re.compile(r"\bT[01]\b")),
    ('"reset"', re.compile(r"\breset\b", re.IGNORECASE)),
]


def test_the_rendered_brief_carries_no_retired_builder_word():
    text = _text(_banner() + _render())
    found = [(name, m.group(0)) for name, pat in _RETIRED for m in pat.finditer(text)]
    assert not found, f"retired builder vocabulary in the brief's human-facing text: {found}"
    # ...and the reader forms are what replaced them.
    assert "Data through Wednesday, June 10" in text and "Thursday, June 11" in text
    assert text.count("Data through") == 1, "ONE freshness line per surface"
    assert "THE ENGINE'S SCORE" in text and "The engine's score 20 → 21" in text
    assert "The seven areas" in text
    assert "Essential-habits streak (days)" in text and "Essential: 5 of 7" in text
    assert "% of essential habits" in text and "over 6 measured days of 7" in text
    assert "last update Friday, June 5 (5 days ago)" in text
    assert "nothing logged since Sunday, April 26 (45 days)" in text


def test_served_coach_text_is_shown_verbatim_even_when_it_uses_a_builder_word():
    """The coach paragraphs are served text: the rulings gloss or label them, never edit
    them. A renderer that "fixed" the vocabulary inside them would be rewriting the coach."""
    html = _render(sleep_coach_v2_text=_SERVED)
    assert _SERVED in _html.unescape(html)


def test_day_in_words_is_the_one_server_side_spelling_and_hands_back_what_it_cannot_parse():
    from common.pacific_time import day_in_words

    assert day_in_words("2026-09-25") == "Friday, September 25"
    assert day_in_words("2026-09-05", weekday=False) == "September 5"  # no zero padding
    assert day_in_words("not-a-date") == "not-a-date"
    assert day_in_words("?") == "?"
