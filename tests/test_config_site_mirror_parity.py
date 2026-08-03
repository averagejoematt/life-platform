"""tests/test_config_site_mirror_parity.py — #2084: one catalog, one cast.

Some registries are published through two prefixes at once: `config/x.json` is
read from S3 by the site-api Lambda, and `site/config/x.json` is shipped as a
static asset by the site sync. Two prefixes, two deploy paths, and — until this
guard — nothing at all tying the two repo files together.

That is not a hypothetical. Measured live 2026-08-03: the bucket-root
`config/challenges_catalog.json` was a pre-#1904 remap onto *retired* personas
(`Dr. Lena Johansson` ×24, `Coach Maya Rodriguez` ×10, `Dr. Kai Nakamura` ×8 …),
while `site/config/challenges_catalog.json` carried the roster-clean 2026-08-01
fix. `/api/challenges` and `/api/challenge_catalog` served the same 82
challenges attributed to two different casts, and every gate was green:
`test_cast_roster_consistency` only knew about the `site/` copy, and the twin
check only knew about objects the repo authored under `config/`.

So the assertion is on the **set**, not the instance: every basename that
exists under BOTH repo `config/` and repo `site/config/` must be byte-identical.
A pair added tomorrow is covered without anyone remembering this file exists,
and the failure message names the drifted pair rather than a generic diff.

Byte equality (not parsed-JSON equality) is deliberate: `config_twin_sync`
compares sha256 of raw bytes, so a reformat that leaves the parse identical
would still show up as live drift there. Judging by the same yardstick keeps
this guard from passing something that check would fail.
"""

import hashlib
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_CONFIG = _REPO / "config"
_SITE_CONFIG = _REPO / "site" / "config"


def _paired_basenames() -> list[str]:
    """Basenames present under BOTH repo `config/` and repo `site/config/`.

    Derived from the trees, never enumerated — the whole point of the guard.
    Top level only: `config/` has subtrees (coaches/, portraits/, narrative/)
    that `site/config/` deliberately does not mirror.
    """
    if not _CONFIG.is_dir() or not _SITE_CONFIG.is_dir():
        return []
    site_names = {p.name for p in _SITE_CONFIG.iterdir() if p.is_file()}
    return sorted(p.name for p in _CONFIG.iterdir() if p.is_file() and p.name in site_names)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_the_paired_set_is_not_empty():
    """An empty pair set would make every assertion below vacuously true.

    The "gate that was never running" shape (#1908/#1920): if the discovery
    ever silently returns nothing — a moved directory, a renamed prefix — this
    file would report green while checking literally nothing.
    """
    paired = _paired_basenames()
    assert paired, "no config/ ↔ site/config/ pairs discovered — the parity guard is inert"
    assert "challenges_catalog.json" in paired, "the #2084 instance dropped out of the discovered set"


@pytest.mark.parametrize("basename", _paired_basenames())
def test_dual_published_registry_is_byte_identical(basename):
    """The API copy and the static copy must be the same bytes."""
    api_copy, static_copy = _CONFIG / basename, _SITE_CONFIG / basename
    api_sha, static_sha = _sha256(api_copy), _sha256(static_copy)
    assert api_sha == static_sha, (
        f"config/{basename} and site/config/{basename} have drifted apart "
        f"({api_sha[:12]}… vs {static_sha[:12]}…).\n"
        "  These are published through two prefixes and read by two endpoints. Diverged, "
        "readers are told two different things about the same registry (#2084 — that is "
        "exactly how /api/challenges and /api/challenge_catalog came to serve two casts).\n"
        f"  Fix by making them equal: cp site/config/{basename} config/{basename} (or the reverse), "
        "then re-run. Do NOT reformat either file — config_twin_sync compares raw bytes."
    )


def test_the_predicate_actually_rejects(tmp_path):
    """Negative control: byte comparison rejects a JSON-equivalent reformat.

    A guard written against `json.load(...) == json.load(...)` would pass this,
    and then `config_twin_sync` would report the object as drifted in S3 — the
    gate saying clean while the deploy path says dirty.
    """
    same_parse_a = tmp_path / "a.json"
    same_parse_b = tmp_path / "b.json"
    same_parse_a.write_text('{"k": 1}')
    same_parse_b.write_text('{\n  "k": 1\n}')
    assert _sha256(same_parse_a) != _sha256(same_parse_b)
