"""tests/test_elena_config_twins_6196.py — the narrator's own entries in the repo-owned config twins agree with the
Elena canon (#6196, owner ruling 2026-11-22 §9).

Elena was defined four ways (#6155); the canon (``content/elena_canon.py``) is the one specification. Her entries in the
board config, the podcast series bible and the persona registry are descriptive only (no prompt reads them for her), but
they sync to S3 on every site deploy, so a stale one is public-repo text that contradicts the series. This test pins the
three entries to the canon's key facts: an AI editorial persona, no career or past outside the series, the canon's length
range, and no journal-access claim. One test, so it counts as one gate.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))

from content import elena_canon  # noqa: E402

# Phrases the canon retired. Each was an invented human identity, a past, a journal-access claim or a stale length.
_RETIRED = (
    "embedded journalist",
    "embedded with matthew",
    "freelance journalist",
    "spent years",
    "interviews the board",
    "board member interviews",
    "emotional weather",
    "1200-1800",
    "1,200-1,800",
)


def _load(rel: str) -> dict:
    return json.loads((_REPO / rel).read_text(encoding="utf-8"))


def _flat(node) -> str:
    return json.dumps(node, ensure_ascii=False).lower()


def test_the_narrators_entries_in_every_config_twin_agree_with_the_canon():
    board = _load("config/board_of_directors.json")["members"]["elena_voss"]
    bible = _load("config/podcast_series_bible.json")["characters"]["elena"]
    persona = _load("config/personas.json")["personas"]["elena_voss"]

    problems = []
    for label, entry in (("board", board), ("bible", bible), ("persona", persona)):
        text = _flat(entry)
        for phrase in _RETIRED:
            if phrase in text:
                problems.append(f"{label}: carries the retired claim {phrase!r}")
        if "ai editorial persona" not in text and "an ai editorial persona" not in text:
            problems.append(f"{label}: does not say Elena is an AI editorial persona")

    rel = board["relationship_to_matthew"].lower()
    if "no career" not in rel or "interviewed no one" not in rel:
        problems.append("board: relationship_to_matthew drops the no-career / no-interview statement")
    if "no career" not in bible.lower():
        problems.append("bible: characters.elena drops the no-career statement")
    if "never reads, quotes or narrates the journal" not in board["voice"]["style"].lower():
        problems.append("board: voice.style drops the no-journal statement")
    if "journal" in " ".join(board["data_sources"]).lower() and "never the journal" not in " ".join(board["data_sources"]).lower():
        problems.append("board: data_sources claims journal access")
    if "compassionate without being soft" not in board["voice"]["tone"].lower():
        problems.append("board: tone drops the owner-kept 'compassionate without being soft'")

    lo, hi = elena_canon.CHRONICLE_BODY_WORDS
    fmt = board["features"]["chronicle"]["format"]
    nums = [int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", fmt)]
    if nums[:2] != [lo, hi]:
        problems.append(f"board: chronicle format {fmt!r} is not the canon range {lo}-{hi}")

    assert not problems, "Elena's config twins drifted from lambdas/content/elena_canon.py:\n  " + "\n  ".join(problems)
