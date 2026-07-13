"""
panelcast_zeitgeist.py — free RSS "zeitgeist" for the Panel podcast (#1178, epic #1082).

A real podcast references the week it's recorded in — a World Cup comeback Matt
could learn from, a quirky story as an aside. This module gives the writer that
ambient awareness at zero marginal cost: ~a dozen BBC headlines (top stories /
sport / culture) fetched over stdlib urllib (the no-external-HTTP-libs rule) and
injected into the writer prompts as an OPTIONAL TOPICAL COLOR block, plus a
matching ground-truth block for the judge so the grounded-generation gate
(ADR-104) never flags a provided headline as an invention.

Posture: strictly fail-soft. Every feed gets a short timeout and a catch-all —
a dead feed, malformed XML, or no network at all just means fewer (or zero)
headlines, and the episode generates exactly as before. The fetch happens ONCE
per run (see coach_panel_podcast_lambda) and the same list is reused across
attempts/revisions so the writer prompt and the judge's ground truth stay
consistent.

Safety: a keyword/category tragedy filter (TRAGEDY_TERMS) drops any grim item
before it ever reaches the writer — the prompt rules additionally forbid quips
on anything grim and partisan advocacy (the bible's compassion_safety_rules).

Kill switch: PANELCAST_ZEITGEIST=off → fetch_zeitgeist() returns [] (the test
suite runs with it off via tests/conftest.py so the unit suite stays hermetic).
"""

import logging
import os
import re
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger()

# BBC's free RSS surface — top stories for the week's texture, sport for the
# comeback/effort analogies the show actually wants, culture for the quirky asides.
ZEITGEIST_FEEDS = (
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.bbci.co.uk/sport/rss.xml",
    "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",
)

FEED_TIMEOUT_SECONDS = 5
MAX_PER_FEED = 4
MAX_TOTAL = 12

# The tragedy filter — an item whose title/description/categories hits ANY of
# these terms is dropped outright (over-filtering is the safe direction: losing
# a quirky headline costs nothing; quipping near a tragedy is unforgivable).
TRAGEDY_TERMS = (
    "abuse",
    "assault",
    "attack",
    "attacked",
    "attacks",
    "bomb",
    "bombing",
    "cancer",
    "casualties",
    "casualty",
    "crash",
    "crashed",
    "crashes",
    "dead",
    "death",
    "deaths",
    "died",
    "dies",
    "disaster",
    "drowned",
    "drowning",
    "dying",
    "earthquake",
    "explosion",
    "famine",
    "fatal",
    "fatality",
    "flood",
    "flooding",
    "funeral",
    "genocide",
    "grief",
    "gunman",
    "hostage",
    "hostages",
    "hurricane",
    "kidnap",
    "kidnapped",
    "kill",
    "killed",
    "killing",
    "landslide",
    "massacre",
    "missing",
    "mourning",
    "murder",
    "murdered",
    "obituary",
    "overdose",
    "rape",
    "shooting",
    "shot",
    "stabbed",
    "stabbing",
    "starvation",
    "suicide",
    "terror",
    "terrorism",
    "terrorist",
    "tragedy",
    "tragic",
    "victim",
    "victims",
    "war",
    "wars",
    "wildfire",
    "wounded",
)

_TRAGEDY_RE = re.compile(r"\b(" + "|".join(TRAGEDY_TERMS) + r")\b", re.IGNORECASE)


def _first_sentence(text: str) -> str:
    """First sentence of an RSS description, whitespace-normalized and capped."""
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    m = re.match(r"(.+?[.!?])(?:\s|$)", t)
    return (m.group(1) if m else t)[:220]


def _parse_feed(raw: bytes) -> list:
    """Filtered headlines from one RSS payload — 'Title — first sentence' strings.

    Raises on malformed XML; the caller's catch-all makes that a skipped feed.
    """
    # noqa justification: stdlib-only bundle (no defusedxml); source is a fixed
    # allowlist of BBC feed URLs, capped in size, and the caller fails soft on any raise.
    root = ET.fromstring(raw)  # noqa: S314
    items = []
    for item in root.iter("item"):
        title = re.sub(r"\s+", " ", item.findtext("title") or "").strip()
        if not title:
            continue
        desc = _first_sentence(item.findtext("description") or "")
        cats = " ".join((c.text or "") for c in item.findall("category"))
        if _TRAGEDY_RE.search(" ".join((title, desc, cats))):
            continue  # never hand the writer anything grim
        items.append(f"{title} — {desc}" if desc else title)
        if len(items) >= MAX_PER_FEED:
            break
    return items


def fetch_zeitgeist(feeds=ZEITGEIST_FEEDS) -> list:
    """~12 filtered headlines from the free feeds. STRICTLY fail-soft: any feed
    error (network, HTTP, XML) just means fewer headlines; [] is a fine result.
    Call ONCE per podcast run and reuse the list for revisions/repairs so the
    writer prompt and the judge's ground truth stay consistent."""
    if os.environ.get("PANELCAST_ZEITGEIST", "on").strip().lower() in ("off", "0", "false"):
        return []
    headlines, seen = [], set()
    for url in feeds:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "life-platform-panelcast/1.0"})
            with urllib.request.urlopen(req, timeout=FEED_TIMEOUT_SECONDS) as resp:
                raw = resp.read()
            for h in _parse_feed(raw):
                if h.lower() in seen:
                    continue
                seen.add(h.lower())
                headlines.append(h)
        except Exception as e:  # fail-soft — the episode never depends on the news
            logger.warning("[panel] zeitgeist feed failed (%s) — %s", url, e)
        if len(headlines) >= MAX_TOTAL:
            break
    return headlines[:MAX_TOTAL]


def zeitgeist_prompt_block(headlines: list) -> str:
    """The OPTIONAL TOPICAL COLOR block for a writer prompt; '' when empty
    (the writer never sees an empty scaffold)."""
    if not headlines:
        return ""
    lines = "\n".join(f"  - {h}" for h in headlines[:MAX_TOTAL])
    return (
        "OPTIONAL TOPICAL COLOR — headlines from the week this episode is recorded (real; use or ignore):\n"
        f"{lines}\n"
        "RULES for these headlines: use at MOST 1-2, and ONLY as light, natural quips or analogies where they genuinely "
        "land (a sport comeback Matt could learn from, a quirky story as an aside) — never load-bearing to the episode's "
        "spine. Add NO details beyond the headline itself. Any such line must still read fine to a listener who missed "
        "the story. Never quip on anything grim. No partisan advocacy — light novelty humor only. If nothing lands "
        "naturally, use none."
    )


def zeitgeist_truth_block(headlines: list) -> str:
    """The judge-side ground-truth block ('' when empty) — labels the fetched
    headlines as REAL provided material so the GROUNDED rubric never flags a
    reference to them as an invention (ADR-104)."""
    if not headlines:
        return ""
    return "\n\nTOPICAL HEADLINES provided to the writer (real, not inventions — do not flag references to them):\n" + "\n".join(
        f"  - {h}" for h in headlines[:MAX_TOTAL]
    )
