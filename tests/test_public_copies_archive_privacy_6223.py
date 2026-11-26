"""tests/test_public_copies_archive_privacy_6223.py — the archive's API copies follow the live publication policy (#6223).

2026-11-26: `scripts/check_public_copies.py --check` passed while the public archive tarball still held route copies with
restraint-derived names and a character method the live routes no longer serve. Rule C (``--check`` red, like the rest of
rule C) now fails an archived ``api/`` copy that carries a word the live policy withholds — the route walk's ONE list,
``character_privacy.withheld_public_tokens`` — or that declares an older character public-method version, and an archive
built before the newest public-method change. A clean archive passes; each must-fail fixture fails by name.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import check_public_copies as C  # noqa: E402
import restraint_route_walk as RW  # noqa: E402
from health import character_privacy as CP  # noqa: E402

NOW = CP.PUBLIC_METHOD_VERSION
EPOCH = max(m.get("defined_on") or "" for m in CP.PUBLIC_METHOD_HISTORY)


def _members(character: dict, config: dict | None = None) -> dict:
    out = {"api/character.json": json.dumps(character).encode()}
    if config is not None:
        out["api/character_config.json"] = json.dumps(config).encode()
    return out


CLEAN_CHAR = {"character": {"status": "recalculating", "method": {"version": NOW, "origin": "live"}}, "pillars": [{"name": "sleep"}]}
CLEAN_CONFIG = {"public_method": {"version": NOW, "history": [{"version": m["version"]} for m in CP.PUBLIC_METHOD_HISTORY]}}
BUILT = {"generated_at": f"{EPOCH}T23:00:00Z"}


def test_a_clean_archive_passes():
    assert C.archive_privacy_issues(_members(CLEAN_CHAR, CLEAN_CONFIG), BUILT) == []


def test_must_fail_an_archived_copy_with_a_withheld_word():
    token = CP.withheld_public_tokens(json.load(open(os.path.join(ROOT, "config", "character_sheet.json"))))[0]
    bad = dict(CLEAN_CHAR, pillars=[{"name": "mind", "drivers": {"top": [token]}}])
    issues = C.archive_privacy_issues(_members(bad, CLEAN_CONFIG), BUILT)
    assert [i[1] for i in issues] == ["C"] and "withholds" in issues[0][2] and "api/character.json" in issues[0][2]


def test_must_fail_an_archived_copy_served_under_an_older_method():
    old = {"character": {"method": {"version": CP.PUBLIC_METHOD_V1}}}
    issues = C.archive_privacy_issues(_members(old, CLEAN_CONFIG), BUILT)
    assert len(issues) == 1 and CP.PUBLIC_METHOD_V1 in issues[0][2]


def test_must_fail_an_archive_built_before_the_newest_method_change():
    issues = C.archive_privacy_issues(_members(CLEAN_CHAR, CLEAN_CONFIG), {"generated_at": "2026-11-01T00:00:00Z"})
    assert len(issues) == 1 and "before the public method change" in issues[0][2]


def test_the_guard_and_the_route_walk_read_one_token_list():
    policy = set(C._withheld_tokens())
    assert policy and policy <= set(RW.tokens())
