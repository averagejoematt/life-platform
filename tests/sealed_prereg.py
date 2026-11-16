"""tests/sealed_prereg.py — where the tests find the sealed cycle-17 pre-registration now that it is private.

The 2026-09-06 pre-registration (sealed SHA-256 below) carries two calls the owner ruled private (#5720), so since the
owner ruling of 2026-11-11 (item 3) the repo no longer carries it, nor its byte-identical fixture, nor the season-row
capture that names those calls. The original is kept privately and unchanged. A test that needs the real bytes reads
them from the directory named by ``LIFE_PLATFORM_PRIVATE_PREREG_DIR`` and only when they hash to the published seal (a
redacted or edited copy is never accepted as the seal); otherwise it skips with ``REASON``.

The published digest itself stays in the repo (deploy/generated/genesis_preregistration.sha256.json).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

ENV = "LIFE_PLATFORM_PRIVATE_PREREG_DIR"
SEALED_NAME = "genesis_preregistration.json"
SEALED_SHA256 = "bd225d24f67381c253a34671107ba1bc1a8a3c9cc35dadbca1a5edd061b9782d"
SEASON_ROWS_NAME = "prereg_season_rows_2026-09-17.json"
SEASON_ROWS_SHA256 = "35a0b6395604202ff789a0ba039bbea284648b511f928d65771be7b9a9060460"
REASON = (
    "the sealed 2026-09-06 pre-registration is private since 2026-11-11 (it carries withdrawn calls); "
    f"set {ENV} to the directory holding the private original to run this"
)


APPROVED_CALLS = Path(__file__).resolve().parent / "fixtures" / "prereg_cycle17_approved_calls.json"


#: The privacy cleanup of 2026-11-11 replaced the wording of six approved calls (they stated the subject's sleep-window
#: and HRV targets) with stand-in text that starts with this marker. A stand-in is never a sealed call's words: those six
#: entries' hashes are matched only against the private original.
STAND_IN = "(stand-in text"


def approved_call_texts() -> list:
    """The day-one calls the CR2 allowlist approves whose words the labelled test copy still carries (never the seal),
    in sealed order — 8 of the 14; the stand-ins are left out."""
    return [c["claim_natural"] for c in json.loads(APPROVED_CALLS.read_text())["calls"] if not c["claim_natural"].startswith(STAND_IN)]


def stand_in_count() -> int:
    """How many approved calls the test copy carries only as stand-in text."""
    return sum(1 for c in json.loads(APPROVED_CALLS.read_text())["calls"] if c["claim_natural"].startswith(STAND_IN))


def with_words(entries) -> list:
    """The allowlist entries whose words are available here: all 14 with the private original, else the 8 approved
    calls the test copy still carries."""
    have = {hashlib.sha256(t.encode("utf-8")).hexdigest() for t in sealed_call_texts()}
    return [e for e in entries if e.text_sha256 in have]


def sealed_call_texts() -> list:
    """Every sealed call's wording: the private original's when available, else only the approved ones the test copy
    still carries (stand-ins excluded)."""
    sealed = load_sealed()
    if sealed is None:
        return approved_call_texts()
    return [p["claim_natural"] for c in sealed["coaches"].values() for p in c["predictions"]]


def _find(name: str, sha256: str) -> Path | None:
    d = os.environ.get(ENV)
    if not d:
        return None
    p = Path(d) / name
    if p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == sha256:
        return p
    return None


def sealed_path() -> Path | None:
    """The private original, only when its bytes are the sealed bytes."""
    return _find(SEALED_NAME, SEALED_SHA256)


def season_rows_path() -> Path | None:
    return _find(SEASON_ROWS_NAME, SEASON_ROWS_SHA256)


def load_sealed() -> dict | None:
    p = sealed_path()
    return json.loads(p.read_text()) if p else None


def require_sealed_path() -> Path:
    p = sealed_path()
    if p is None:
        pytest.skip(REASON)
    return p


def require_season_rows_path() -> Path:
    p = season_rows_path()
    if p is None:
        pytest.skip(REASON)
    return p
