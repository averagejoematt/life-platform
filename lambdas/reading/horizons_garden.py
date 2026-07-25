"""horizons_garden.py — the Horizons curation "garden" (#1705, epic #1686 S1).

Horizons is the weekly, coach-curated media pick that broadens Matthew's
horizons (any format, any pillar). The **Mind coach** owns it but ranges broadly
across all pillars.

Sourcing (owner decision, 2026-07-25) is NOT a narrow allow-list — that was too
predictable. It is a *broad curated garden* grouped by category that the coach
ranges freely across (and may reach outside for topical items), paired with a
**link-verification gate** (`horizons_verify.py`) that fetches every pick's URL
and confirms it resolves to real content before the pick is stored/publishable
(fail-closed). The garden is the trusted-outlet reference set; the verification
gate is what satisfies ADR-104 (no fabricated / unresolvable links).

Data-driven + easily editable by design: `GARDEN` is a plain list of dicts (the
reading rail's constants-module idiom — cf. `reading_onboarding.QUESTION_BANK`,
`reading_recall.INTERVALS`). Matthew edits this list directly; a garden entry is
just {name, category, domain}. Nothing here reaches out to the network — this
module is a pure constants table.
"""

from __future__ import annotations

# ── The format enum (owner-widened, 2026-07-25) ───────────────────────────────
# A pick can be any of these; `article` is the catch-all written form.
FORMATS = (
    "article",
    "podcast",
    "video",
    "paper",
    "news",
    "longform",
    "essay",
    "song",
)

# ── The rationale tag — WHY this pick, this week ───────────────────────────────
# topical            → of-the-moment (news, a new release, a cultural beat)
# experiment-relevant → speaks to what Matthew is actually testing right now
RATIONALE_TAGS = ("topical", "experiment-relevant")

# ── The curator ───────────────────────────────────────────────────────────────
# The Mind coach owns Horizons but curates broadly across every pillar.
CURATOR = "mind"

# ── The garden: trusted outlets grouped by category ───────────────────────────
# Broad, not narrow. Group by category; the coach ranges freely across it. This
# is a starting set — Matthew broadens/edits it directly. Each entry carries a
# `domain` (bare host, no scheme) so a pick's URL can be sanity-checked against
# the garden if we ever want to, without constructing links here.
GARDEN: list[dict] = [
    # ── Health / performance ──────────────────────────────────────────────────
    {"name": "Peter Attia — The Drive", "category": "health", "domain": "peterattiamd.com"},
    {"name": "Huberman Lab", "category": "health", "domain": "hubermanlab.com"},
    {"name": "Examine.com", "category": "health", "domain": "examine.com"},
    {"name": "FoundMyFitness (Rhonda Patrick)", "category": "health", "domain": "foundmyfitness.com"},
    {"name": "Stronger by Science", "category": "health", "domain": "strongerbyscience.com"},
    {"name": "Barbell Medicine", "category": "health", "domain": "barbellmedicine.com"},
    # ── Mind / experimentation ────────────────────────────────────────────────
    {"name": "Ness Labs", "category": "mind", "domain": "nesslabs.com"},
    {"name": "Experimental History", "category": "mind", "domain": "experimental-history.com"},
    {"name": "Astral Codex Ten", "category": "mind", "domain": "astralcodexten.com"},
    {"name": "Greater Good (UC Berkeley)", "category": "mind", "domain": "greatergood.berkeley.edu"},
    # ── Meaning / fulfillment ─────────────────────────────────────────────────
    {"name": "The Marginalian (Maria Popova)", "category": "meaning", "domain": "themarginalian.org"},
    {"name": "Oliver Burkeman", "category": "meaning", "domain": "oliverburkeman.com"},
    {"name": "The Growth Equation", "category": "meaning", "domain": "thegrowtheq.com"},
    # ── Science / progress ────────────────────────────────────────────────────
    {"name": "Nature Human Behaviour", "category": "science", "domain": "nature.com"},
    {"name": "Works in Progress", "category": "science", "domain": "worksinprogress.co"},
    {"name": "Quanta Magazine", "category": "science", "domain": "quantamagazine.org"},
    # ── News / investigative ──────────────────────────────────────────────────
    {"name": "Reuters", "category": "news", "domain": "reuters.com"},
    {"name": "Associated Press", "category": "news", "domain": "apnews.com"},
    {"name": "ProPublica", "category": "news", "domain": "propublica.org"},
    {"name": "The Atlantic (longform)", "category": "news", "domain": "theatlantic.com"},
    # ── Culture / music / video ───────────────────────────────────────────────
    # YouTube is allowed as a video source; song/lyrics picks are permitted
    # (format="song") — a lyric can broaden horizons as much as an essay.
    {"name": "YouTube (video picks)", "category": "culture", "domain": "youtube.com"},
    {"name": "Genius (song / lyrics)", "category": "culture", "domain": "genius.com"},
    {"name": "NPR Music", "category": "culture", "domain": "npr.org"},
]


def categories() -> list[str]:
    """The distinct categories present in the garden, in first-seen order."""
    seen: list[str] = []
    for entry in GARDEN:
        cat = entry.get("category")
        if cat and cat not in seen:
            seen.append(cat)
    return seen


def by_category() -> dict[str, list[dict]]:
    """The garden grouped by category → [entry, ...]."""
    out: dict[str, list[dict]] = {}
    for entry in GARDEN:
        out.setdefault(entry.get("category", "uncategorized"), []).append(entry)
    return out


def is_valid_format(fmt: str) -> bool:
    return fmt in FORMATS


def is_valid_rationale(tag: str) -> bool:
    return tag in RATIONALE_TAGS
